"""What counts as a secret in a Paste's text.

The project had no list of credential shapes to reuse, so `credentials.py` is
the list. Two ways: real-shaped fakes are caught, and the words people write
every day are not -- a Paste that is wrongly called secret fails whenever the
keyring is down. No token below is real; each is built in pieces so that no
secret scanner takes this file for a leak.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import credentials

A = "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5"      # 36 mixed characters


def caught():
    return {
        "anthropic": "sk-" + "ant-api03-" + A + "_" + A,
        "openai": "sk-" + "proj-" + A,
        "openai old": "sk-" + A + "12",
        "github classic": "gh" + "p_" + A,
        "github oauth": "gh" + "o_" + A,
        "github fine grained": "github_" + "pat_" + "11ABCDEFG0" + A + "_" + A,
        "slack": "xox" + "b-123456789012-1234567890123-" + A[:24],
        "aws key id": "AK" + "IA" + "ABCDEFGH23456723",
        "aws temporary": "AS" + "IA" + "ABCDEFGH23456723",
        "google": "AI" + "za" + "Sy" + A[:33],
        "jwt": "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0." + "dBjftJeZ4CVPmB92K27uhbUJU1p1r",
        "pem": "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA\n-----END " + "RSA PRIVATE KEY-----",
        "pem openssh": "-----BEGIN OPENSSH " + "PRIVATE KEY-----\nb3BlbnNzaC1rZXk=\n",
        "bearer": "Authorization: Bearer " + A,
        "url credentials": "postgres://app:" + "hunter2hunter2" + "@db.internal:5432/app",
        "password assignment": "password=" + "Tr0ub4dor&3x",
        "password colon quoted": 'db_password: "' + "correct-horse-9-battery" + '"',
        "env style": "export STRIPE_API_KEY=" + "pk9f3k2j4h5g6f7d",
        "token in json": '{"token": "' + "a1b2c3d4e5f6g7h8" + '"}',
        "password with a dot": "password=" + "correct." + "horse",
        "plain password": "password=" + "letmein" + "please",
        "plain token": "token=" + "abcdefghi" + "jklmno",
        "quoted plain": 'password: "' + "letmein" + 'please"',
        "long word password": "password=" + "correcthorse" + "batterystaple",
        "token letters only": "token=" + "abcdefghijklmnop" + "qrstuvwxyz",
        "stripe style": "STRIPE_SECRET_KEY=" + "sk_live_" + "abcdefghijklmnopqrstuvwxyz",
        "tailscale": "tskey-" + "auth-" + "kAbCdEfGh1CNTRL-" + A[:20],
        "google oauth": "ya" + "29." + A + "_" + A,
        "google client secret": "GOC" + "SPX-" + A[:28],
        "stripe live": "sk" + "_live_" + A[:24],
        "stripe webhook": "whsec" + "_" + A[:24],
        "gitlab": "glpat" + "-" + A[:20],
        "hugging face": "hf" + "_" + A,
        "npm": "npm" + "_" + A,
        "slack app": "xapp" + "-1-" + A[:30],
        "slack webhook": "https://hooks.slack" + ".com/services/T01ABCDEF/B02GHIJKL/" + A[:24],
        "sendgrid": "SG" + "." + A[:22] + "." + A[:22],
        "lowercase bearer": "authorization: bear" + "er " + A,
        "dollar in password": "password=" + "Pa$$w0rd2024!",
        "flemish": "paswoord: " + "Tulpen2026!",
        "is form": "The password is " + "Tulpen2026x",
        "curl user": "curl -u " + "sven:Tulpen2026 https://example.com",
        "long flag": "mytool --pass" + "word Tulpen2026 --x",
        "dutch": "Het wachtwoord: " + "Zomer2026!xyz" + " voor de router",
    }


class Caught(unittest.TestCase):
    def test_each_shape_is_caught_alone_and_inside_other_text(self):
        for label, text in caught().items():
            with self.subTest(label):
                self.assertTrue(credentials.looks_secret(text), label)
                self.assertTrue(credentials.looks_secret(f"Hoi Sven,\n\nhier is het:\n{text}\n\ngroet"), label)


PROSE = [
    "Hoi Sven, kun je de policy vandaag nog bekijken? Groet, Thierry",
    "Please set a password in the keyring and keep the token short-lived.",
    "Zet het wachtwoord in de keyring en deel het niet via mail.",
    "The token: expires tomorrow, the password: is in the vault.",
    "password: see the vault",
    "token = None",
    "password=$DB_PASSWORD",
    "--token=${TOKEN}",
    'curl -H "Authorization: Bearer $TOKEN" https://example.com/api',
    "export PATH=/usr/local/bin:$PATH",
    "ssh-keygen -t ed25519 -C thierry@example.com",
    "git log --oneline 8d7b2de..HEAD   # 8d7b2de0123456789abcdef0123456789abcdef0",
    "the risk-assessment-framework-for-2026-planning and a task-management-system-overview-v2",
    "sk-learn is spelled scikit-learn; desk-research-notes-2026-10-21-final-version",
    "sha256:" + "0123456789abcdef" * 4,
    "https://example.com/a/very/long/path/with-many-parts/and-more-parts-1234567890/index.html",
    "user@example.com:~/Projects/agentview$ python3 -m unittest tests.test_paste -v",
    '{"acls": [{"action": "accept", "src": ["tag:admin"], "dst": ["*:*"]}], "ssh": []}',
    "API keys are rotated every 90 days; ask for a new key at the desk.",
    "Authorization: Bearer <your token here>",
    "-----BEGIN PGP SIGNATURE-----\nnot a private key\n-----END PGP SIGNATURE-----",
    "postgres://app@db.internal:5432/app",
    "AKIA is the prefix of an access key id; ASIA the temporary kind.",
    "De 'password reset' mail kwam niet aan; the 'secret' sauce is the cache.",
    "line one\nline two with tabs\t and \"quotes\" and 'apostrophes' \\ backslashes\n",
    "token_count=123items and password_policy_version=Version2 and access_key_rotation=every90days",
    "tokens: 12.5k/200k used",
    "cd $PWD; PWD=/home/alice/Projects/maple",
    "Maak een token aan: https://github.com/settings/tokens",
    "password=$DB_PASSWORD and token=${TOKEN} and pwd=$(pwd)",
    "The password is in the vault and the wachtwoord is verlopen.",
    "curl -u thierry https://example.com and --token $TOKEN and --password-stdin",
    "secretary=Ilse, max_tokens=4096",
    "The secret is base64-encoded. The token is OAuth2-based. Het token is SHA256-gehasht.",
    "docker exec -u www-data:www-data app ls; docker build --secret id=npmrc,src=$HOME/.npmrc .",
    "paste create abc --title \"Mail\" --secret /tmp/mail.txt",
    "A" * 5000,
    "",
]


class NotCaught(unittest.TestCase):
    def test_ordinary_prose_commands_and_ids_are_not_secrets(self):
        for text in PROSE:
            with self.subTest(text[:50]):
                self.assertFalse(credentials.looks_secret(text), text[:80])

    def test_a_hundred_kilobytes_of_one_kind_of_character_is_scanned_in_linear_time(self):
        import time
        for text in ("1" * 100_000, "_" * 100_000, "a1" * 50_000, "token" * 20_000, "password=" + "a1" * 50_000,
                     "sk-" + "1" * 100_000, "Bearer " + "a" * 100_000, "://" + "a" * 100_000,
                     "sk-" * 33_000, "Bearer " * 14_000, "://a:" * 20_000, "password=" * 11_000, "sk-a" * 25_000,
                     "AKIA" * 25_000, "eyJ" * 33_000, "-----BEGIN " * 9_000, "_eyJ" * 25_000, ("-eyJ" + "a" * 10) * 7_000):
            started = time.monotonic()
            credentials.looks_secret(text)
            self.assertLess(time.monotonic() - started, 2, text[:12])

    def test_a_non_string_is_not_a_secret(self):
        self.assertFalse(credentials.looks_secret(None))


if __name__ == "__main__":
    unittest.main()
