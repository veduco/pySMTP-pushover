import re
import time
import base64
import email.utils
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from core.config import MAX_TITLE_CHARS, MAX_ATTACHMENT_BYTES

def _recover_defective_lines(part, base_text):
    """Extracts and prepends text recovered from MIME structure defects."""
    if not part.defects:
        return base_text
    recovered_lines = []
    for defect in part.defects:
        if getattr(defect, 'line', None):
            line_str = defect.line.decode('utf-8', errors='replace').strip() if isinstance(defect.line, bytes) else defect.line.strip()
            recovered_lines.append(line_str)
    if recovered_lines:
        return '\n'.join(recovered_lines) + '\n' + base_text
    return base_text

def parse_email_content(raw_content):
    """
    Extracts, decodes, and sanitizes MIME email parts into a clean Gateway payload format.
    """
    raw_content = re.sub(br'(Content-Type:\s*[^;\r\n]+;\r?\n)(charset=)', br'\1 \2', raw_content, flags=re.IGNORECASE)
    raw_content = re.sub(br'(charset="?[a-zA-Z0-9\-]+"?\r?\n)(?!\r?\n|[ \t]*--|[A-Za-z0-9\-]+:|[ \t]+[A-Za-z0-9\-]+=)', br'\1\r\n', raw_content, flags=re.IGNORECASE)

    msg = message_from_bytes(raw_content, policy=policy.default)
    title = msg.get("Subject", "No Subject")
    if len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS]

    timestamp = int(time.time())
    date_header = msg.get("Date")
    if date_header:
        try:
            timestamp = int(parsedate_to_datetime(date_header).timestamp())
        except Exception:
            pass

    plain_body_raw = ""
    html_body_raw = ""
    valid_images = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition"))
            if content_type.startswith("image/"):
                payload_bytes = part.get_payload(decode=True)
                if payload_bytes:
                    size = len(payload_bytes)
                    if size <= MAX_ATTACHMENT_BYTES:
                        valid_images.append((size, str(part.get_filename() or "image.jpg"), content_type, payload_bytes))
                continue

            if "attachment" in content_disposition:
                continue

            if content_type == "text/plain":
                body_decoded = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
                plain_body_raw = _recover_defective_lines(part, body_decoded)
            elif content_type == "text/html":
                html_body_raw = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
    else:
        raw_payload = msg.get_payload(decode=True)
        content_type = msg.get_content_type()
        if content_type.startswith("image/"):
            if raw_payload:
                size = len(raw_payload)
                if size <= MAX_ATTACHMENT_BYTES:
                    valid_images.append((size, str(msg.get_filename() or "image.jpg"), content_type, raw_payload))
        else:
            decoded_str = raw_payload.decode(msg.get_content_charset() or 'utf-8', errors='replace') if raw_payload else ""
            if content_type == "text/html":
                html_body_raw = decoded_str
            else:
                plain_body_raw = _recover_defective_lines(msg, decoded_str)

    best_image = None
    if valid_images:
        valid_images.sort(key=lambda x: (-x[0], x[1]))
        best_image = valid_images[0]

    body_html_processed = None
    if html_body_raw:
        processed = re.sub(r'<(style|script|head|title)[^>]*>.*?</\1>', '', html_body_raw, flags=re.IGNORECASE | re.DOTALL)
        parts = re.split(r'(?i)(<pre[^>]*>.*?</pre>)', processed, flags=re.DOTALL)
        for i in range(len(parts)):
            if not parts[i].lower().startswith('<pre'):
                parts[i] = re.sub(r'[\r\n\t]+', ' ', parts[i])
                parts[i] = re.sub(r'<br\s*/?>', '\n', parts[i], flags=re.IGNORECASE)
                parts[i] = re.sub(r'</(p|div|tr|h[1-6]|li|table)>', '\n\n', parts[i], flags=re.IGNORECASE)
                parts[i] = re.sub(r'<hr[^>]*>', '\n---\n', parts[i], flags=re.IGNORECASE)
                parts[i] = re.sub(r'<(?!/?(a|b|i|u|font)\b)[^>]+>', '', parts[i], flags=re.IGNORECASE)
                parts[i] = re.sub(r' {2,}', ' ', parts[i])
                parts[i] = re.sub(r' ?\n ?', '\n', parts[i])
            else:
                parts[i] = re.sub(r'(?i)</?pre[^>]*>', '', parts[i])
        body_html_processed = ''.join(parts)
        body_html_processed = re.sub(r'\n{3,}', '\n\n', body_html_processed).strip()

    body_plain_processed = None
    if plain_body_raw:
        body_plain_processed = re.sub(r'(\r?\n[ \t]*){3,}', '\n\n', plain_body_raw).strip()

    return {
        "title": title,
        "timestamp": timestamp,
        "best_image": best_image,
        "body_html_processed": body_html_processed,
        "body_plain_processed": body_plain_processed
    }

def build_test_email(data):
    """Centralized constructor for UI test payload injections with native defaults."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg['Subject'] = "Test Payload"
    msg['From'] = data.get("from") or "user@example.com"
    msg['To'] = data.get("to") or "user@example.com"

    payload_type = data.get("type") or "multipart"
    plain_msg = data.get("message_plain") or "Test message from SMTP Gateway"
    html_msg = data.get("message_html") or "<html><body><p>Test message from SMTP Gateway</p></body></html>"

    if payload_type == "plaintext":
        msg.set_content(plain_msg)
    elif payload_type == "html":
        msg.set_content(html_msg, subtype="html")
    else:  # multipart fallback
        msg.set_content(plain_msg)
        msg.add_alternative(html_msg, subtype="html")

    attachments = data.get("attachments", [])
    for att in attachments:
        try:
            file_data = base64.b64decode(att.get("data", ""))
            mime_type = att.get("type", "application/octet-stream")

            # Safely split mime type into maintype and subtype for the email constructor
            if "/" in mime_type:
                maintype, subtype = mime_type.split("/", 1)
            else:
                maintype, subtype = "application", "octet-stream"

            msg.add_attachment(
                file_data,
                maintype=maintype,
                subtype=subtype,
                filename=att.get("name", "test_attachment.bin")
            )
        except Exception as e:
            print(f"Failed to process test attachment {att.get('name')}: {e}")

    return msg

class MIMEBuilder:
    """Dedicated builder class to safely deconstruct and reconstruct MIME payloads based on delivery constraints."""

    @staticmethod
    def rebuild_payload_bytes(payload: dict, force_plaintext: bool, include_attachments: bool) -> bytes:
        raw_bytes = base64.b64decode(payload["raw_eml_base64"])
        original_msg = message_from_bytes(raw_bytes, policy=policy.default)

        # Always enforce a structurally valid RFC 5322 From header for egress relays
        orig_from = str(original_msg.get('From', ''))
        name, _ = email.utils.parseaddr(orig_from)
        clean_sender = payload.get("sender", "gateway@localhost")
        safe_from = email.utils.formataddr((name, clean_sender))

        del original_msg['From']
        original_msg['From'] = safe_from

        # If no structural mutation is requested, return the pristine original bytes (with fixed header)
        if not force_plaintext and include_attachments:
            return bytes(original_msg)

        raw_plain = ""
        raw_html = ""

        # Walk the tree to strip attachments and extract pristine text payloads
        for part in original_msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            if "attachment" in str(part.get("Content-Disposition", "")).lower():
                continue

            ctype = part.get_content_type()
            if ctype == "text/plain":
                raw_plain = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')
            elif ctype == "text/html":
                raw_html = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='replace')

        msg = EmailMessage()

        # Clone original headers safely, excluding structural boundaries and the old From header
        for key, val in original_msg.items():
            if key.lower() not in ['content-type', 'mime-version', 'content-transfer-encoding', 'content-disposition', 'from']:
                msg[key] = val

        msg['From'] = safe_from

        if 'MIME-Version' not in msg:
            msg['MIME-Version'] = '1.0'

        # Ensure missing essential headers are populated
        if not msg.get('Subject'): msg['Subject'] = payload.get("title", "No Subject")
        if not msg.get('To'): msg['To'] = ", ".join(payload.get("recipients", []))
        if not msg.get('Date'): msg['Date'] = email.utils.formatdate(localtime=False)
        if not msg.get('Message-ID'): msg['Message-ID'] = email.utils.make_msgid()

        # Apply structural constraints
        if force_plaintext:
            msg.set_content(raw_plain or payload.get("message", ""), charset="utf-8")
        else:
            msg.set_content(raw_plain or payload.get("message", ""), charset="utf-8")
            if raw_html:
                msg.add_alternative(raw_html, subtype="html", charset="utf-8")

        if include_attachments and payload.get("attachment_base64"):
            img_bytes = base64.b64decode(payload["attachment_base64"])
            maintype, subtype = payload.get("attachment_type", "application/octet-stream").split('/', 1)
            msg.add_attachment(img_bytes, maintype=maintype, subtype=subtype, filename=payload.get("attachment_name", "attachment"))

        return bytes(msg)
