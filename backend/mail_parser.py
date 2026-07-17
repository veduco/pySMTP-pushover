import re
import time
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
        # Natively establishes text/html without throwing wrapping tags around it
        msg.set_content(html_msg, subtype="html")
    else:  # multipart fallback
        msg.set_content(plain_msg)
        msg.add_alternative(html_msg, subtype="html")

    return msg
