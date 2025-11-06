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
