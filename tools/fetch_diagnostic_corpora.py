"""Fetch and verify the public TELBench and AgentRx diagnostic corpora."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

TELBENCH_REVISION = "307d870d7424be265653bb7a566793cc217105be"
TELBENCH_FILES = ("TELBench.jsonl.enc", "TELBench.jsonl.enc.sha256",
                  "TELBench.jsonl.sha256", "TELBench.passphrase.txt")
AGENTRX_REVISION = "f228165bfec60a801fd5fedd9d8ffe0f9de0c69d"
AGENTRX_REPOSITORY = "microsoft/AgentRx"
AGENTRX_FIXED = ("data/tau_retail/tau_dataset_failed.json",
                 "data/ground_truth/tau_ground_truth.json",
                 "data/ground_truth/magentic_one_ground_truth.json")


def download(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "ReplayGuard-diagnostic-corpora/1.0"})
    with urlopen(request, timeout=180) as response:
        return response.read()


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def expected_checksum(body: bytes) -> str:
    value = body.decode("utf-8").strip().split()[0].lower()
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("upstream checksum file does not contain a SHA-256 digest")
    return value


def decrypt_telbench(ciphertext: bytes, passphrase: bytes) -> bytes:
    """Decrypt the upstream OpenSSL aes-256-cbc/pbkdf2/200000 release format."""
    from cryptography.hazmat.primitives import hashes, padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    if not ciphertext.startswith(b"Salted__") or len(ciphertext) < 32:
        raise ValueError("TELBench ciphertext is not an OpenSSL salted envelope")
    salt, encrypted = ciphertext[8:16], ciphertext[16:]
    key_iv = PBKDF2HMAC(algorithm=hashes.SHA256(), length=48, salt=salt,
                       iterations=200_000).derive(passphrase.strip())
    decryptor = Cipher(algorithms.AES(key_iv[:32]), modes.CBC(key_iv[32:])).decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def fetch_telbench(root: Path) -> dict:
    base = f"https://huggingface.co/datasets/NJU-LINK/TELBench/resolve/{TELBENCH_REVISION}"
    bodies = {name: download(f"{base}/{name}") for name in TELBENCH_FILES}
    if sha256(bodies["TELBench.jsonl.enc"]) != expected_checksum(bodies["TELBench.jsonl.enc.sha256"]):
        raise RuntimeError("TELBench encrypted checksum mismatch")
    plaintext = decrypt_telbench(bodies["TELBench.jsonl.enc"], bodies["TELBench.passphrase.txt"])
    if sha256(plaintext) != expected_checksum(bodies["TELBench.jsonl.sha256"]):
        raise RuntimeError("TELBench decrypted checksum mismatch")
    target = root / "telbench" / "TELBench.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(plaintext)
    records = sum(bool(line.strip()) for line in plaintext.splitlines())
    return {"repository": "NJU-LINK/TELBench", "revision": TELBENCH_REVISION,
            "license": "Apache-2.0", "path": target.relative_to(root).as_posix(),
            "sha256": sha256(plaintext), "records": records}


def fetch_agentrx(root: Path) -> dict:
    api = f"https://api.github.com/repos/{AGENTRX_REPOSITORY}/git/trees/{AGENTRX_REVISION}?recursive=1"
    tree = json.loads(download(api))["tree"]
    magentic = sorted(item["path"] for item in tree if item.get("type") == "blob"
                      and item["path"].startswith("data/magentic_dataset/")
                      and item["path"].endswith(".json")
                      and Path(item["path"]).name not in {"magentic_count.json", "steps_by_id.json"})
    paths = [*AGENTRX_FIXED, *magentic]
    raw = f"https://raw.githubusercontent.com/{AGENTRX_REPOSITORY}/{AGENTRX_REVISION}/"
    files = []
    for source in paths:
        body = download(raw + source)
        target = root / "agentrx" / source
        target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(body)
        files.append({"path": target.relative_to(root).as_posix(), "sha256": sha256(body), "bytes": len(body)})
    return {"repository": AGENTRX_REPOSITORY, "revision": AGENTRX_REVISION,
            "license": "MIT", "files": files, "magentic_trajectories": len(magentic)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=".verify/upstream/diagnostic-corpora")
    parser.add_argument("--corpus", choices=("all", "telbench", "agentrx"), default="all")
    args = parser.parse_args(argv); root = Path(args.output)
    manifest = {"format": 1, "sources": {}}
    if args.corpus in {"all", "telbench"}:
        manifest["sources"]["telbench"] = fetch_telbench(root)
    if args.corpus in {"all", "agentrx"}:
        manifest["sources"]["agentrx"] = fetch_agentrx(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
