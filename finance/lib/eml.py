"""Write an email draft as an .eml file with attachments, from a JSON spec.

Open the .eml in Apple Mail and use Message > Send Again to get an editable
copy with the attachments in place. Nothing is sent by this script.

usage: python3 lib/eml.py spec.json out.eml
spec: {"from": ["Name", "addr"], "to": [["Name", "addr"], ...], "cc": [...],
       "subject": "...", "body": "plain text", "attachments": ["path.pdf", ...]}
"""
from __future__ import annotations
import json
import mimetypes
import sys
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path


def build(spec: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr(tuple(spec["from"]))
    msg["To"] = ", ".join(formataddr(tuple(a)) for a in spec["to"])
    if spec.get("cc"):
        msg["Cc"] = ", ".join(formataddr(tuple(a)) for a in spec["cc"])
    msg["Subject"] = spec["subject"]
    msg["Date"] = formatdate(localtime=True)
    msg["X-Unsent"] = "1"
    msg.set_content(spec["body"].rstrip() + "\n", charset="utf-8")
    for path in spec.get("attachments", []):
        p = Path(path)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    return msg


if __name__ == "__main__":
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build(spec).as_bytes())
    print("draft written:", out, f"({out.stat().st_size // 1024} KB)")
