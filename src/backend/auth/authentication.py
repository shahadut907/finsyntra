"""
JWT Authentication system for FinSyntra RAG Chatbot
Handles user authentication, token creation, and validation
"""
from datetime import datetime, timedelta, timezone
import uuid
from typing import Optional, Dict, Any
import jwt
from passlib.context import CryptContext

from src.config.settings import settings


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token
    """
    to_encode = data.copy()
    
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire, "iat": now})
    if to_encode.get("type") == "refresh":
        to_encode.setdefault("jti", str(uuid.uuid4()))
    
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.secret_key, 
        algorithm=settings.algorithm
    )
    
    return encoded_jwt


def verify_token(token: str) -> Dict[str, Any]:
    """
    Verify and decode JWT token
    """
    try:
        payload = jwt.decode(
            token, 
            settings.secret_key, 
            algorithms=[settings.algorithm],
            options={"require": ["exp", "sub"]},
        )
        return payload
    except jwt.PyJWTError:
        raise Exception("Invalid token")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hash
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password
    """
    return pwd_context.hash(password)


# Test authentication functions
if __name__ == "__main__":
    print("[*] Testing Authentication System")
    print("=" * 40)
    
    # Test token creation and verification
    test_data = {"sub": "test@finsolve.com", "role": "employee"}
    
    print("[*] Creating test token...")
    token = create_access_token(test_data)
    print(f"[+] Token created: {token[:50]}...")
    
    print("\n[*] Verifying token...")
    try:
        payload = verify_token(token)
        print(f"[+] Token verified successfully")
        print(f"   Subject: {payload.get('sub')}")
        print(f"   Role: {payload.get('role')}")
        print(f"   Expires: {datetime.fromtimestamp(payload.get('exp'))}")
    except Exception as e:
        print(f"[-] Token verification failed: {e}")
    
    # Test password hashing
    print("\n🔒 Testing password hashing...")
    test_password = "test123"
    hashed = get_password_hash(test_password)
    print(f"[+] Password hashed: {hashed[:50]}...")
    
    # Test password verification
    print("\n[+] Testing password verification...")
    is_valid = verify_password(test_password, hashed)
    print(f"[+] Password verification: {is_valid}")
    
    print("\n[+] Authentication system test completed!")
