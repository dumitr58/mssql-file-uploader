# MSSQL File Uploader — xp_cmdshell Payload Delivery via Base64 Encoding

## Overview
**MSSQL File Uploader** is a Python tool for penetration testers who have credentials for a Microsoft SQL Server account with `xp_cmdshell` enabled.  
It uploads local files to a Windows host by writing Base64-encoded chunks via `xp_cmdshell` (`echo >> file`) and writes helper decode scripts (SQL and command snippets) so the operator can reconstruct the binary on the target using the least-intrusive method available.

> **Use case:** You are tunneled into a network and cannot or do not want to open new ports / services on the target. Instead of enabling SSH or SMB, this tool uses `xp_cmdshell` to deliver payloads reliably.

## Features
- Chunked Base64 upload using `xp_cmdshell` via Impacket MSSQL client
- Multiple decode helper files generated automatically (certutil, PowerShell, SQL)
- Per-chunk retries and configurable chunk size
- Supports SQL and Windows authentication modes (Impacket)
- Clear instructions for safe decode and hash verification

## Requirements
- Python 3.8+
- [Impacket](https://github.com/fortra/impacket) installed and on PATH:
  - `pip install impacket`
  - Ensure `impacket-mssqlclient` or `mssqlclient.py` is runnable

## Installation
Clone the repository and ensure requirements:
```bash
git clone https://github.com/dumitr58/mssql-file-uploader.git
cd mssql-file-uploader
pip install -r requirements.txt   # requirements.txt can contain: impacket
```

## Usage
```
python3 uploader_write_decode_cmds.py <host> <username> <password> <local_file> --target "C:\\Users\\Public" [options]
```

## Example
```
python3 uploader_write_decode_cmds.py 10.10.205.148 "oscp.exam/sql_svc" 'Dolphin1' /home/kali/payload.exe --target "C:\\Users\\Public" --windows-auth
```

## Common options
--chunk-size (default 1000) — base64 characters per upload chunk
--retries (default 1) — retries per chunk
--per-chunk-timeout (default 60) — timeout for each impacket invocation
--windows-auth — use Impacket windows-auth mode
--outdir — where to write decode helper files (default: decode_commands)

## Output
The script uploads <local_file>.b64 to the remote path you specify (or default C:\Windows\Temp).
It writes helper files locally in decode_commands/ to guide decoding on the target (decode_certutil.sql, powershell_cmd.txt, gethash_sql.sql, etc.)

## Decoding recommendations
1. Use the SQL files with Impacket -file (safer for quoting and length). Example:
```
impacket-mssqlclient "user:pass@host" -file decode_commands/decode_certutil.sql
```
2. If you have interactive access on the host, run certutil -decode or the PowerShell one-liner present in powershell_cmd.txt.
3. Always verify SHA256 after decoding. Example helper in gethash_sql.sql.

## Security & Legal
Only use this tool on systems you are explicitly authorized to test.
Unauthorized use is illegal and unethical. Keep authorization documentation for all engagements.

## Contributing
Contributions welcome open issues or pull requests for bugfixes and improvements. Please follow the project's CONTRIBUTING.md for guidelines.
