# agentview — da claude-team a un dashboard multi-agente

**2026-09-22 · design, non ancora implementato · rivisto dopo la review di Codex**

Il progetto diventa pubblico e smette di parlare solo con Claude Code. Il nome nuovo è
`agentview`, repo e pacchetto. Il prodotto non è più la pagina: è il contratto che la
riempie, perché chi aggiunge un provider è un agente, non una persona che legge un README.

**Piattaforma: Linux.** Non è una scelta nuova, è quello che il codice già impone —
`/proc`, Konsole via D-Bus in `jump.py`, l'unità systemd. Il README deve dirlo, perché il
provider Codex ci si appoggia ancora di più.

---

## Cosa entra nella prima versione

**v1 dimostra che l'astrazione funziona.** Claude e Codex come provider dentro il repo,
importati dal core. Niente `pyproject.toml`, niente `entry_points`, niente suite di
conformance, niente `PROVIDERS.md` pubblicato.

**Dopo**, quando il contratto ha retto due provider veri: packaging, `entry_points`, la
lista di path in `config.json`, la conformance, la spec pubblica.

Il motivo: un contratto disegnato su due provider che girano è diverso da uno disegnato
sulla carta, e pubblicare `entry_points` prima di averlo verificato lega a una firma che
poi va rotta. La sezione "La scoperta dei provider" più sotto descrive il dopo, non il
primo commit.

---

## Quello che c'è oggi

`fleet.py` legge due cose per sessione e costruisce tutto il resto sopra:

| Cosa | Da dove |
|---|---|
| chi è vivo, e come sta | `~/.claude/sessions/*.json` — pid, status, name, tmux, cwd, `waitingFor` |
| di cosa si tratta, cosa ha detto | il transcript `~/.claude/projects/<cwd-encoded>/<sid>.jsonl`, letto in coda incrementale |

La pagina fa poll ogni 3 secondi (`index.html:989`). Il front-end dipende da **circa 31
campi per sessione**, più i campi derivati e quelli di blocco. **La liveness è il pid**:
`fleet.py:106` fa `os.kill(pid, 0)` e `sessions()` scarta chiunque non risponda.

### `server.py` è Claude-specifico quanto `fleet.py`

Questo il documento lo aveva sbagliato: elencava `server.py` fra le cose che non si toccano.
Non è così, ed è la correzione più costosa della review.

- `_jump` valida il pid con `fleet.live_session(pid)` — una funzione che legge i peer file
  di Claude. Il browser manda solo un pid, che non è né globalmente unico nel tempo né
  disponibile per ogni provider.
- **`seen.mark()` sta solo dentro `_jump`** (`server.py:107`). Una sessione che non si può
  cliccare non si segna mai letta, quindi resta `ready` per sempre e il contatore in cima
  non torna a zero.
- `_line` — la rinomina della scheda — indicizza `s["pid"]` e `s["tmux"]` senza condizioni
  (`server.py:177`).
- `seen.forget(live)` gira a ogni poll (`server.py:186`): un provider che fallisce un giro
  cancella le conferme di lettura delle sue sessioni, che al ritorno tornano `ready`.

### Cosa si riusa e cosa si riscrive

Da riscrivere per provider: `transcript_for`, `scan_cached` / `_absorb`, `live_session`,
`sessions`, `routine_of`, `boss_line`.

Da adattare, non da riusare così com'è: `classify` (chiede il silenzio del transcript, la
durata del tool in volo, `waitingFor` e lo stato di letto — niente di tutto questo è nel
contratto, e conosce la semantica `shell` che è solo di Claude), e i tre punti di
`server.py` qui sopra.

Resta com'è: `roster`, `order_blocks`, `apply_overrides`, `resolve_project`, `jump.py`, e le
funzioni che danno forma al testo — `last_words`, `ask_from`, `own_line`.

---

## I tre agenti, misurati

Tutto quello che segue è stato verificato su questa macchina il 2026-09-22, non dedotto.

### Claude Code

Registro dei vivi con pid e status, transcript per sessione, hook che scrivono le due righe
(`hooks/team-line`, agganciato in `settings.json:45` e `:81`). È il caso completo, ed è il
motivo per cui il contratto va progettato sugli altri due.

Nota: `/api/roster` non è letto da nessuno tranne il browser. Il `/boss` costruisce la sua
roster da `boss-lifecycle.sh list --mine` e `ListAgents`.

### Codex

- `~/.codex/state_5.sqlite`, tabella `threads`, 542 righe: `id`, `cwd`, `git_branch`,
  `title`, `first_user_message`, `preview`, `updated_at_ms`, `rollout_path`, `model`,
  `tokens_used`.
- `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` — JSONL append-only, stessa forma del
  transcript Claude. Gli `event_msg` utili sono `task_started`, `user_message`,
  `agent_message`, `task_complete`.
- Il rollout con `session_meta` (cwd compreso) **viene scritto all'avvio**, prima della
  risposta del modello: una prova fallita sul limite d'uso ha lasciato lo stesso 47 KB su
  disco.
- **`~/.codex/thread-writer-locks/<thread-id>.lock`** compare quando la sessione parte e
  sparisce quando finisce pulita.
- **Il lock resta orfano dopo un `SIGKILL`** — verificato. La liveness vera è "il lock
  esiste **e** qualcuno ne tiene l'fd aperto".
- Un processo vivo tiene aperto il proprio rollout in `/proc/<pid>/fd`, e il nome del file
  contiene il thread id. Il match pid↔sessione è esatto.
- Nessun nome: `agent_nickname` è NULL su tutte e 542 le righe. Il `title` è il primo prompt
  troncato.
- Uso reale su questa macchina: **479 `exec`, 56 subagent di review, 7 interattive**.

**Il limite dell'fd aperto**: prova che un processo sta scrivendo quel thread, non che il
suo terminale rappresenti ancora quella sessione. E `/proc/*/fd` fallisce sotto `hidepid`,
in container, o per un processo di un altro utente. In quei casi il provider Codex degrada:
la sessione compare senza `jump`. Non inventa un pid.

### opencode

Non è installato qui. Quello che segue viene dalla lettura del sorgente in
`anomalyco/opencode` (ex `sst/opencode`), v1.18.32.

- Store primario SQLite: `~/.local/share/opencode/opencode.db`, tabella `session` con `id`,
  `title`, `directory`, `agent`, `model`, `cost`, `tokens_*`, `time_created`, `time_updated`.
- **Nessuna colonna per il branch git.**
- `GET /session/status` restituisce `{sessionID: {type: "idle"|"busy"|"retry"}}`.
- Sotto la TUI interattiva **gira sempre un server HTTP locale**. Porta 4096 se libera,
  altrimenti una a caso.
- Stream SSE su `GET /global/event`, con l'evento `session.status`.
- Hook: solo plugin JS/TS. **Nessun modo di lanciare un comando shell su un evento.**
- Niente pid, niente lock, niente socket.

**Due problemi non risolti, ed è il motivo per cui opencode non è in v1.** La porta è
casuale e non c'è registro che dica quale processo la serve, quindi non esiste una
scoperta. E `/session/status` è un'istantanea: dice `idle` adesso, non *quando* è diventata
idle — che è quello che serve a `updatedAt`. Ricavarlo vuol dire tenere aperto lo stream SSE
e persistere le transizioni, cosa che un `live()` sincrono non può fare. Chi scriverà quel
provider parte da qui.

### La simmetria che detta il contratto

Codex ti dà il disco e ti nega lo stato. opencode ti dà lo stato e ti nega il disco. Nessuno
dei due ti dà un nome.

---

## Le decisioni

| # | Decisione | Scelta |
|---|---|---|
| 1 | Per chi è il codice | **Pubblico** |
| 2 | Cosa merita una scheda | **Tutto elencato**, come oggi per Claude |
| 3 | opencode | **Ipotetico**: si progetta per due, se ne implementa uno |
| 4 | Forma del contratto | **Classe Python** con metodi separati |
| 5 | Campi obbligatori | **Nucleo minimo + capability dichiarate** |
| 6 | Schede effimere | **Niente**: nascono e muoiono, è la verità della macchina |
| 7 | Liveness | **Il provider si arrangia**, il core non sa come |
| 8 | Dove vive la spec | **`PROVIDERS.md` + suite di conformance** — dopo v1 |
| 9 | Nome | **`agentview`**, repo e pacchetto — libero su PyPI |
| 10 | Il click | **Pid al core**, che riusa `jump.py`; `jump()` come override |
| 11 | Le due righe senza hook | **Ripiego** sull'ultima frase dell'agente |
| 12 | Chiave di sessione | **`provider:id`** composta |
| 13 | Capability | **Cinque, dichiarate dal provider** + `extras` libero |
| 14 | Chi modella il testo | **Il core**: il provider dà i fatti, il core dà la voce |
| 16-17 | Scoperta dei provider | **`entry_points` + path in `config.json`** — dopo v1 |
| 18 | Scope della v1 | **Far funzionare Claude + Codex**, packaging dopo |
| 19 | Segnare letta | **Il click basta**, anche senza terminale |

---

## Il contratto

```python
class Provider:
    name: str                    # "claude", "codex" — i due punti sono vietati
    capabilities: set[str]       # jump, branch, waiting, name, status

    def live(self) -> list[Session]:
        """Le sessioni vive adesso. Come lo sappia è affar suo."""

    def jump(self, session) -> dict | None:
        """Override. None = il core usa il pid e jump.py.
        Se implementato ritorna {"ok": bool, "reason": str} — la pagina
        mostra già `reason` quando il salto fallisce."""
```

### Campi obbligatori

| Campo | Significato |
|---|---|
| `id` | unico **e stabile** dentro il provider; la chiave globale è `provider:id` |
| `provider` | il nome del provider, senza due punti |
| `cwd` | da cui il core ricava il progetto, con le shelves di oggi |
| `status` | `busy` \| `idle` \| `waiting` |
| `updatedAt` | **millisecondi epoch**, l'istante in cui ha cambiato stato |

Due campi valgono un paragrafo perché sono quelli che si sbagliano.

**`updatedAt` non è l'ultima attività.** `seen.py` ci aggancia il tick azzurro del "ha finito
e non l'hai ancora letta": se un provider ci mette l'ultima attività, il tick non si spegne
mai. Il tipo è millisecondi epoch, come tutto il resto del codice — la pagina ci fa
aritmetica e ordinamento diretto.

**`id` deve essere stabile, non solo unico.** Il letto, le righe scritte a mano,
l'assegnazione a un progetto, la piegatura dei blocchi e il chime pendono tutti
dall'identità che regge fra un poll e l'altro e fra un riavvio e l'altro. Un id che cambia a
ogni poll fa suonare il chime all'infinito.

### Campi opzionali

`pid`, `name`, `branch`, `title`, `prompt`, `said`, `waitingFor`, `startedAt`, `kind`.

Il core li normalizza: `sessions()` riempie di default ogni campo che il front-end consuma e
che il provider non ha dato. Nessuna sessione conforme deve poter far esplodere `roster()`
con un `KeyError`.

### Le capability

Cinque, dichiarate dal provider: `jump`, `branch`, `waiting`, `name`, `status`. Dicono cosa
quel provider sa e cosa non saprà mai, e servono a distinguere un dato mancante da un dato
che non esisterà — una scheda Claude senza branch è una sessione fuori da un repo, una
scheda opencode senza branch è un campo che quel provider non avrà mai.

**Due di queste cinque cambiano il comportamento del core** e vanno trattate come rami di
codice, non come etichette:

- **`waiting`** — senza, il chime non può suonare per quel provider.
- **`jump`** — senza, la scheda non è cliccabile per saltare (ma resta cliccabile per
  segnarla letta, vedi sotto).

Le altre tre sono dichiarative. `status` è anche obbligatorio come campo: la capability dice
se il provider distingue davvero i tre stati o se ne conosce due.

**`extras: dict[str, str]`**, chiavi libere, che la pagina mostra come badge senza sapere
cosa significhino — `cost: "$0.42"`, `model: "gpt-5.5"`. Nessuno tocca `index.html`, quindi
nessuna installazione forka la pagina. Limiti: al massimo 8 chiavi, 40 caratteri per valore,
ordinate alfabeticamente. Un provider che ne manda mille non deve poter rallentare un poll da
3 secondi né sfondare il layout.

### Le due righe

Per Claude le scrive l'hook. Per gli altri il provider restituisce il **testo grezzo**
dell'ultimo messaggio dell'agente in `said`, e il core lo modella con `last_words`,
`ask_from` e `own_line`.

**Il ripiego non è equivalente all'hook, e va detto.** `own_line` ritorna `"blocked": False`
sul ramo del ripiego (`fleet.py:545`): una domanda ricavata dall'ultima frase riempie le
parole ma non alza il conteggio e non fa suonare niente. Un provider senza hook mostra il
testo giusto e non ti chiama mai. È esattamente il motivo per cui vale la pena scrivere
l'hook, e la pagina deve renderlo visibile invece di nasconderlo.

---

## Il salto, e il segnare letta

Sono due gesti diversi sullo stesso click, e oggi sono lo stesso codice.

**Il salto.** Il browser manda la **chiave globale** `provider:id`, non il pid. Il server
risolve il provider, gli richiede quella sessione per confermare che è ancora viva, e poi:
se il provider ha un `jump()` lo chiama, altrimenti prende il `pid` e usa `jump.py`. La
ricerca del pane — WezTerm, tmux, Konsole — resta nel core, altrimenti il quarto provider
avrà il jump rotto.

**Il segnare letta.** `seen.mark()` esce da `_jump` e diventa una chiamata sua, invocata dal
click qualunque cosa il click faccia dopo. Guardare è guardare, che il terminale venga avanti
o no.

**La rinomina** (`_line`) passa dalla stessa risoluzione: chiede al provider la sessione, e
se non ha pid né tmux rinomina solo la riga in `config.json` senza toccare nessun terminale.
Oggi indicizza `s["pid"]` e `s["tmux"]` alla cieca.

---

## Quando un provider si rompe

Un solo provider non deve poter abbattere la pagina. Un errore di import, un SQLite bloccato,
una richiesta HTTP lenta, un'eccezione qualsiasi:

- ogni `live()` gira con un **timeout** e dentro un `try`;
- un provider che fallisce sparisce dalla pagina con un **badge di stato**, gli altri
  restano;
- **`seen.forget()` non cancella** le conferme di lettura di un provider che ha fallito quel
  giro, solo quelle dei provider che hanno risposto. Altrimenti un giro perso fa tornare
  `ready` tutto quello che avevi già letto.

E poiché `server.py` è un `ThreadingHTTPServer`, due poll possono sovrapporsi mentre i
provider scrivono le loro cache, scansionano `/proc` o interrogano SQLite. La cache globale
in `fleet.py:61` è già senza lock oggi. Il poll va serializzato con un lock unico.

---

## La scoperta dei provider (dopo v1)

- **Claude e Codex stanno nel repo** e li importa il core. Non hanno bisogno di essere
  scoperti. Questo è tutto quello che c'è in v1.
- **`entry_points`** per chi pubblica: un terzo mette `agentview-<nome>` su PyPI, l'utente fa
  `pip install`, il core lo trova da solo. Richiede prima un `pyproject.toml`, un namespace
  di pacchetto, un nome per il gruppo di entry point e un numero di versione dell'API
  provider — niente di questo esiste oggi.
- **Lista di path in `config.json`** per chi non pubblica: un provider privato per un agente
  interno resta sulla macchina.

All'installazione l'agente chiede una cosa sola: lo pubblichi o resta qui.

## La conformance (dopo v1)

`pytest tests/conformance.py --provider <nome>` è il verde che l'agente deve raggiungere.
Verifica i campi obbligatori e il loro tipo, la stabilità di `id` fra due chiamate, la
semantica di `updatedAt`, e che `waiting` e `jump` dichiarate siano sostenute da quello che
serve. Le chiavi di `extras` si controllano solo nella forma e nel numero.

---

## Cosa cambia nel codice esistente

- `sessions()` diventa l'unione dei `live()` dei provider, **più una normalizzazione** che
  riempie ogni campo che il front-end consuma.
- `alive(pid)` smette di essere il filtro globale e diventa uno strumento che un provider può
  usare.
- `classify()` prende dal contratto quello che oggi prende dal transcript, e i segnali che un
  provider non ha si spengono invece di valere zero.
- `server.py`: `_jump` risolve per chiave e non per pid, `seen.mark()` diventa una chiamata
  propria, `_line` degrada senza terminale, `seen.forget()` rispetta i provider falliti.
- `config.json`: le 4 righe di `assign` scritte a mano vanno migrate a chiavi `provider:id`.
  Lo stesso per `lines` e per `seen.json`.
- `index.html`: manda la chiave invece del pid, renderizza i badge `extras`, degrada le
  schede senza `branch`, `name` o jump.
- **La rinomina del progetto tocca più di quanto sembri**: `seen.py:18` scrive sotto
  `claude-team`, `server.py:209` inizializza il log dalla directory di Claude, l'unità
  systemd si chiama `claude-team.service`, e `index.html:204` ha dentro il nome del prodotto
  e `/home/alice`.
- `hooks/team-line` diventa l'hook del provider Claude, non del progetto.

---

## Cosa resta da verificare prima di scrivere codice

1. **Gli hook di Codex.** Esistono — c'è il flag `--dangerously-bypass-hook-trust` — ma non
   ho provato né gli eventi né il formato. Serve per l'equivalente di `team-line`.
2. **Il titolo automatico di opencode.** La generazione a partire dal primo messaggio è
   documentata dalla community, non trovata nel sorgente.
3. **Il costo dello scan `/proc` a 3 secondi** con più provider attivi. Oggi il warm sta a
   0,03s e quel numero è nel README come argomento.
