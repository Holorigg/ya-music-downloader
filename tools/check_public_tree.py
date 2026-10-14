"""Check the Git index for accidental private files before publication.

Reads staged blobs, never runtime folders. Findings show paths and line numbers,
not credential values. Public application parameters in the API client are
distinct from a user's OAuth access and refresh tokens.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = "android/gradle/wrapper/gradle-wrapper.jar"
WRAPPER_SHA256 = "81a82aaea5abcc8ff68b3dfcb58b3c3c429378efd98e7433460610fecd7ae45f"
PRIVATE_SUFFIXES = {
    ".mp3", ".flac", ".ogg", ".m4a", ".lrc", ".m3u8", ".db", ".sqlite",
    ".sqlite3", ".log", ".apk", ".aab", ".p12", ".jks", ".keystore", ".exe",
    ".dll", ".whl", ".part", ".pyc", ".zip",
}
PRIVATE_FOLDERS = {
    ".venv", "__pycache__", ".gradle", ".gradle-user", "build", "dist",
    "signing", "sdk", "downloads", "cover_cache", "lyrics_cache", "backups",
    ".codex", ".agents", ".claude", ".cursor",
}
PRIVATE_NAMES = {
    "local.properties", "key.properties", "settings.json", "music_status.json",
    "covers_status.json", "relocation.json", "device.json", "auth.json",
    "token.json", ".env", "agents.md", "claude.md", "gemini.md",
}
TEXT_SUFFIXES = {
    ".py", ".java", ".xml", ".md", ".txt", ".gradle", ".properties",
    ".ps1", ".cmd", ".bat", ".yml", ".yaml", ".json", ".pro",
}
TOKEN_PATTERN = re.compile(r"\b(?:y0_[A-Za-z0-9_-]{40,}|AQAAA[A-Za-z0-9_-]{50,})\b")
USER_PATH_PATTERN = re.compile(r"(?i)[a-z]:[\\/]Users[\\/](?!Public\b|Default\b)[^\s\"'<>]+")
PRIVATE_KEY_PATTERN = re.compile("-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def git(*arguments: str) -> bytes:
    result = subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True)
    if result.returncode:
        raise RuntimeError("Cannot read the Git index; stage the source files first.")
    return result.stdout


def main() -> int:
    names = git("ls-files", "-z").decode("utf-8").split("\0")
    names = [name for name in names if name]
    if not names:
        print("No staged or tracked source files. Run git add before this check.")
        return 1
    findings: list[str] = []
    for name in names:
        path = PurePosixPath(name)
        lowered = name.lower()
        if (path.suffix.lower() in PRIVATE_SUFFIXES
                or any(part.lower() in PRIVATE_FOLDERS for part in path.parts)
                or path.name.lower() in PRIVATE_NAMES
                or "_private.json" in lowered
                or path.name.startswith(".env.") and path.name != ".env.example"):
            findings.append(f"{name}: private data or build output")
            continue
        data = git("show", ":" + name)
        if path.suffix.lower() == ".jar":
            if name != WRAPPER or hashlib.sha256(data).hexdigest() != WRAPPER_SHA256:
                findings.append(f"{name}: unrecognised binary archive")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name not in {
            "LICENSE", "gradlew", ".gitignore", ".gitattributes",
        }:
            continue
        try:
            content = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            findings.append(f"{name}: source is not UTF-8")
            continue
        for number, line in enumerate(content.splitlines(), 1):
            for pattern, label in (
                (TOKEN_PATTERN, "possible user OAuth token"),
                (PRIVATE_KEY_PATTERN, "private key"),
                (USER_PATH_PATTERN, "personal absolute path"),
            ):
                if pattern.search(line):
                    findings.append(f"{name}:{number}: {label}")
    if findings:
        print("Public tree check failed:\n" + "\n".join(findings))
        return 1
    print(f"Public tree check passed: {len(names)} Git files; wrapper checksum verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
