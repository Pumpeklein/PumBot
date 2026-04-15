from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

def make_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="transcripts-v1")

def create_transcript_token(secret_key: str, transcript_id: str, user_id: int) -> str:
    s = make_serializer(secret_key)
    # Packe nur das Nötigste rein
    return s.dumps({"tid": transcript_id, "uid": user_id})

def verify_transcript_token(secret_key: str, token: str, max_age_seconds: int) -> dict | None:
    s = make_serializer(secret_key)
    try:
        data = s.loads(token, max_age=max_age_seconds)
        return data
    except (SignatureExpired, BadSignature):
        return None
