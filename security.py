from cryptography.fernet import Fernet, InvalidToken


def _fernet(key: str):
    if not key:
        return None
    return Fernet(key.encode('utf-8'))


def encrypt_text(value: str | None, key: str) -> str | None:
    if not value:
        return None
    f = _fernet(key)
    if not f:
        return 'plain:' + value
    return 'fernet:' + f.encrypt(value.encode('utf-8')).decode('utf-8')


def decrypt_text(value: str | None, key: str) -> str | None:
    if not value:
        return None
    if value.startswith('plain:'):
        return value[6:]
    if value.startswith('fernet:'):
        f = _fernet(key)
        if not f:
            raise RuntimeError('TOKEN_ENCRYPTION_KEY no está configurada.')
        try:
            return f.decrypt(value[7:].encode('utf-8')).decode('utf-8')
        except InvalidToken as exc:
            raise RuntimeError('No se pudo descifrar el token OAuth.') from exc
    return value
