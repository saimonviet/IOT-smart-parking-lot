"""Chứng chỉ TLS tự ký cho cổng HTTPS/WSS và vân tay SHA-256 để Pi ghim (certificate pinning)."""
import hashlib
import ipaddress
import os
import socket
from datetime import datetime, timedelta, timezone

from . import config


def local_ips():
    ips = {"127.0.0.1"}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # UDP: không gửi gói nào, chỉ để biết IP mạng LAN
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        ips.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    return sorted(ips)


def ensure_cert():
    """Tạo chứng chỉ tự ký nếu chưa có. Trả về True nếu vừa tạo mới."""
    if config.TLS_CERT.exists() and config.TLS_KEY.exists():
        return False
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    config.TLS_DIR.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "smart-parking-server")])
    sans = [x509.DNSName("localhost"), x509.DNSName(socket.gethostname())]
    sans += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in local_ips()]
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    config.TLS_KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                 serialization.NoEncryption()))
    try:
        os.chmod(config.TLS_KEY, 0o600)
    except OSError:
        pass
    config.TLS_CERT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return True


def fingerprint():
    """SHA-256 của chứng chỉ (dạng DER), giống giá trị Pi tính được khi bắt tay TLS."""
    import ssl
    der = ssl.PEM_cert_to_DER_cert(config.TLS_CERT.read_text())
    return hashlib.sha256(der).hexdigest()
