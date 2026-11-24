"""
Production Database Layer for FinSyntra
Supports PostgreSQL for production and SQLite for development
"""

import os
import uuid
import mimetypes
from pathlib import Path
import logging
from typing import Optional, Dict, Any, List
from sqlalchemy import create_engine, Column, String, Integer, DateTime, Text, Boolean, JSON, Index
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func
from datetime import datetime, timedelta, timezone
import redis
import json
from src.config.settings import settings
from src.config.database_url import is_postgres_url, require_postgres_driver

logger = logging.getLogger(__name__)


def build_database_engine(database_url: Optional[str], *, debug: bool = False):
    """Deterministic database engine selection.

    - No DATABASE_URL configured -> the local SQLite development default.
    - Explicit non-PostgreSQL URL (e.g. sqlite://...) -> used exactly as given.
    - Explicit PostgreSQL URL -> PostgreSQL, or a loud failure. Never a
      silent downgrade to SQLite.
    """
    if not database_url:
        db_path = "data/finsolve.db"
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        return create_engine(f"sqlite:///{db_path}", echo=debug)

    if is_postgres_url(database_url):
        require_postgres_driver()
        return create_engine(
            database_url,
            pool_size=20,
            max_overflow=0,
            pool_pre_ping=True,
            echo=debug,
        )

    return create_engine(database_url, echo=debug)


# Database setup
engine = build_database_engine(settings.database_url, debug=settings.debug)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database Models
class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    role = Column(String, nullable=False, default="employee")
    tenant_id = Column(String, nullable=True, index=True)
    department = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_public_demo = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)
    meta = Column("metadata", JSON, default=dict)

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("idx_chat_sessions_tenant_user", "tenant_id", "user_id"),
        Index("idx_chat_sessions_tenant_user_visitor", "tenant_id", "user_id", "visitor_session_id"),
    )

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    # Nullable only for unresolved historical rows. Every new write path below
    # requires a concrete, authenticated tenant.
    tenant_id = Column(String, nullable=True)
    # Extra ownership partition key for PUBLIC-DEMO accounts only (Phase 3).
    # NULL for every non-demo session — unchanged ownership semantics there.
    # For a public-demo session, this holds the server-issued vsid cookie
    # value of the browser that created it; a NULL here is legacy/unresolved
    # and must never be treated as "belongs to the current demo visitor".
    visitor_session_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    is_active = Column(Boolean, default=True)
    meta = Column("metadata", JSON, default=dict)

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    message_type = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    sources = Column(JSON, default=list)
    meta = Column("metadata", JSON, default=dict)

class Document(Base):
    __tablename__ = "documents"
    
    id = Column(String, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    tenant_id = Column(String, nullable=True, index=True)
    storage_path = Column(String, nullable=True)
    title = Column(String, nullable=True)
    content_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=True)
    department = Column(String, nullable=False)
    clearance_level = Column(Integer, default=1)
    uploaded_by = Column(String, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    processed_at = Column(DateTime(timezone=True), nullable=True)
    chunk_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    is_protected_demo = Column(Boolean, nullable=False, default=False)
    meta = Column("metadata", JSON, default=dict)


class RefreshToken(Base):
    """Server-side refresh credential state used for rotation and replay denial."""
    __tablename__ = "refresh_tokens"

    jti = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True, index=True)
    replaced_by = Column(String, nullable=True)

class SessionFact(Base):
    __tablename__ = "session_facts"
    
    id = Column(String, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    fact_key = Column(String, nullable=False)
    fact_value = Column(String, nullable=False)
    source_document = Column(String, nullable=True)
    confidence = Column(Integer, default=100)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    meta = Column("metadata", JSON, default=dict)

class SystemMetrics(Base):
    __tablename__ = "system_metrics"
    
    id = Column(String, primary_key=True, index=True)
    metric_name = Column(String, nullable=False, index=True)
    metric_value = Column(String, nullable=False)
    metric_type = Column(String, nullable=False)  # 'counter', 'gauge', 'histogram'
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    meta = Column("metadata", JSON, default=dict)


class ConversationAccessError(ValueError):
    """Base class for fail-closed conversation ownership failures."""


class ConversationNotFoundError(ConversationAccessError):
    """The session is absent from, or deliberately hidden from, this tenant."""


class ConversationForbiddenError(ConversationAccessError):
    """The session exists in the tenant but belongs to another user."""

# Redis setup for caching
redis_client = None
if settings.redis_url:
    try:
        redis_client = redis.from_url(settings.redis_url)
        redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.warning(f"Redis connection failed: {e}")
        redis_client = None

class DatabaseManager:
    """Production database manager with caching"""
    
    def __init__(self):
        self.redis = redis_client
    
    def get_db(self) -> Session:
        """Get database session"""
        db = SessionLocal()
        try:
            return db
        except Exception:
            db.close()
            raise
    
    def close_db(self, db: Session):
        """Close database session"""
        db.close()
    
    # User management
    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username with caching"""
        cache_key = f"user:username:{username}"
        
        # Try cache first
        if self.redis:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    if "metadata" in data and "meta" not in data:
                        data["meta"] = data.pop("metadata")
                    return User(**data)
            except Exception:
                pass
        
        # Query database
        db = self.get_db()
        try:
            user = db.query(User).filter(User.username == username).first()
            
            # Cache result
            if user and self.redis:
                try:
                    user_data = {
                        "id": user.id,
                        "username": user.username,
                        "email": user.email,
                        "hashed_password": user.hashed_password,
                        "full_name": user.full_name,
                        "role": user.role,
                        "department": user.department,
                        "is_active": user.is_active,
                        "meta": user.meta or {}
                    }
                    self.redis.setex(cache_key, 300, json.dumps(user_data))  # 5 min cache
                except Exception:
                    pass
            
            return user
        finally:
            self.close_db(db)
    
    def create_user(self, user_data: Dict[str, Any]) -> User:
        """Create new user"""
        db = self.get_db()
        try:
            if "metadata" in user_data and "meta" not in user_data:
                user_data["meta"] = user_data.pop("metadata")
            user = User(**user_data)
            db.add(user)
            db.commit()
            db.refresh(user)
            
            # Invalidate cache
            if self.redis:
                cache_key = f"user:username:{user.username}"
                self.redis.delete(cache_key)
            
            return user
        finally:
            self.close_db(db)
    
    # Session management
    @staticmethod
    def _require_ownership(user_id: str, metadata: Dict = None) -> str:
        """Resolve the owning tenant for a NEW session, or refuse to create it.

        Every persisted session must carry a real owner. There is no "default"
        fallback and no request-supplied override: the tenant reaches us from
        server-side authenticated identity via the caller's metadata, and if it
        is absent we fail closed rather than create an unowned row that no
        tenant-scoped query could ever return.
        """
        tenant_id = ((metadata or {}).get("tenant_id") or "").strip()
        if not (user_id or "").strip():
            logger.error("SESSION_CREATE_REJECTED reason=missing_user_id")
            raise ValueError("Cannot create a chat session without a user identity")
        if not tenant_id:
            logger.error("SESSION_CREATE_REJECTED reason=missing_tenant_id user_id=%s", user_id)
            raise ValueError(
                "Cannot create a chat session without an authenticated tenant"
            )
        if tenant_id == "default":
            logger.error("SESSION_CREATE_REJECTED reason=phantom_default_tenant user_id=%s", user_id)
            raise ValueError(
                "'default' is not a real tenant; refusing to create an unowned session"
            )
        return tenant_id

    @staticmethod
    def _require_session_id(session_id: str) -> str:
        resolved = (session_id or "").strip()
        if not resolved:
            raise ValueError("Cannot persist a chat exchange without a session id")
        return resolved

    @staticmethod
    def _assert_session_owner(
        session: ChatSession,
        user_id: str,
        tenant_id: str,
        visitor_session_id: Optional[str] = None,
    ) -> None:
        """Apply the same ownership rule used by every API read/write path.

        Tenant mismatch (including NULL historical ownership) is hidden as a
        not-found condition. A same-tenant, different-user collision is a
        forbidden condition. Both derive from ValueError for compatibility
        with older callers while allowing API routes to map them precisely.

        ``visitor_session_id`` is the extra Phase 3 partition key, and it is
        ONLY ever checked when the caller passes one (i.e. the caller is an
        authenticated public-demo account — see auth_deps.require_visitor_
        session_for_demo). Passing None here means "not a demo caller" and
        leaves non-demo ownership semantics completely unchanged.

        When it IS provided, a mismatch — including a legacy row whose
        visitor_session_id is NULL, or another visitor's value — is treated
        as NOT FOUND, never FORBIDDEN. Every demo visitor shares the exact
        same user_id, so a 403 here would confirm "this id exists under my
        shared account" to anyone who can log in with that same public
        identity: a direct enumeration oracle. Folding it into 404 avoids
        both that oracle and any silent exposure of old shared history.
        """
        if not session.tenant_id:
            raise ConversationNotFoundError(
                f"Session {session.id} has unresolved ownership"
            )
        if session.tenant_id != tenant_id:
            raise ConversationNotFoundError("Conversation not found")
        if session.user_id != user_id:
            raise ConversationForbiddenError(
                f"Session {session.id} belongs to another user"
            )
        if visitor_session_id is not None and session.visitor_session_id != visitor_session_id:
            raise ConversationNotFoundError(
                f"Session {session.id} belongs to another visitor session"
            )

    def _invalidate_chat_history(
        self, session_id: str, user_id: str, tenant_id: str,
        visitor_session_id: Optional[str] = None,
    ) -> None:
        if not self.redis:
            return
        try:
            pattern = f"chat_history:{tenant_id}:{user_id}:{visitor_session_id or ''}:{session_id}:*"
            keys = list(self.redis.scan_iter(match=pattern))
            if keys:
                self.redis.delete(*keys)
        except Exception as exc:
            logger.warning("Failed to invalidate chat history cache: %s", exc)

    def create_chat_session(
        self, user_id: str, session_id: str, metadata: Dict = None,
        visitor_session_id: Optional[str] = None,
    ) -> ChatSession:
        """Create new chat session with tenant isolation"""
        session_id = self._require_session_id(session_id)
        tenant_id = self._require_ownership(user_id, metadata)
        db = self.get_db()
        try:
            existing = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if existing:
                self._assert_session_owner(existing, user_id, tenant_id, visitor_session_id)
                raise ValueError(f"Session {session_id} already exists")
            session = ChatSession(
                id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                visitor_session_id=visitor_session_id,
                meta={**(metadata or {}), "tenant_id": tenant_id}
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            return session
        except Exception:
            db.rollback()
            raise
        finally:
            self.close_db(db)

    def ensure_chat_session(
        self, user_id: str, session_id: str, metadata: Dict = None,
        visitor_session_id: Optional[str] = None,
    ) -> ChatSession:
        """Get existing chat session or create it if missing.

        SECURITY: If session exists, verify the caller owns it.
        Raises a ValueError subtype on ownership mismatch so API callers can
        distinguish hidden cross-tenant sessions from same-tenant denial.
        """
        session_id = self._require_session_id(session_id)
        tenant_id = self._require_ownership(user_id, metadata)

        # A duplicate primary-key race is recoverable: the winner establishes
        # ownership, then the loser re-reads and applies the exact same rule.
        for attempt in range(2):
            db = self.get_db()
            try:
                session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
                if session:
                    self._assert_session_owner(session, user_id, tenant_id, visitor_session_id)
                    if metadata:
                        session.meta = {
                            **(session.meta or {}),
                            **metadata,
                            "tenant_id": tenant_id,
                        }
                        db.commit()
                        db.refresh(session)
                    return session

                session = ChatSession(
                    id=session_id,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    visitor_session_id=visitor_session_id,
                    meta={**(metadata or {}), "tenant_id": tenant_id},
                )
                db.add(session)
                db.commit()
                db.refresh(session)
                return session
            except IntegrityError:
                db.rollback()
                if attempt == 0:
                    continue
                raise
            except Exception:
                db.rollback()
                raise
            finally:
                self.close_db(db)

        raise RuntimeError("Unable to establish chat session ownership")
    
    def add_chat_message(
        self, session_id: str, user_id: str, message_type: str,
        content: str, sources: List = None, metadata: Dict = None,
        visitor_session_id: Optional[str] = None,
    ) -> ChatMessage:
        """Add one message after verifying the exact session owner.

        Normal request paths should use ``persist_chat_exchange`` so the user
        and assistant messages commit atomically. This method remains for
        administrative/test callers and is fail-closed on ownership.
        """
        session_id = self._require_session_id(session_id)
        tenant_id = self._require_ownership(user_id, metadata)
        if message_type not in {"user", "assistant"}:
            raise ValueError("message_type must be 'user' or 'assistant'")
        if not isinstance(content, str) or not content:
            raise ValueError("Chat message content must be a non-empty string")
        db = self.get_db()
        try:
            import uuid
            session = (db.query(ChatSession)
                       .filter(ChatSession.id == session_id)
                       .with_for_update()
                       .first())
            if not session:
                raise ConversationNotFoundError("Conversation not found")
            self._assert_session_owner(session, user_id, tenant_id, visitor_session_id)
            message = ChatMessage(
                id=str(uuid.uuid4()),
                session_id=session_id,
                user_id=user_id,
                message_type=message_type,
                content=content,
                sources=sources or [],
                meta={**(metadata or {}), "tenant_id": tenant_id}
            )
            db.add(message)
            # Touch session updated_at for recency
            session.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(message)
            self._invalidate_chat_history(session_id, user_id, tenant_id, visitor_session_id)
            return message
        except Exception:
            db.rollback()
            raise
        finally:
            self.close_db(db)

    def persist_chat_exchange(
        self,
        session_id: str,
        user_id: str,
        tenant_id: str,
        user_role: str,
        query: str,
        response: str,
        sources: List = None,
        visitor_session_id: Optional[str] = None,
        assistant_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """Atomically persist one delivered user/assistant exchange.

        ``assistant_meta`` carries non-sensitive generation facts (the model
        alias/effort that produced the answer). It can never override the
        tenant binding.

        The session row and both messages share one transaction. If any flush
        or commit fails, no partial user message, assistant message, or newly
        created session remains. ``SELECT .. FOR UPDATE`` serializes exchanges
        for an existing session on databases that support row locks, preserving
        chronological order under concurrent requests.
        """
        import uuid

        session_id = self._require_session_id(session_id)
        tenant_id = self._require_ownership(
            user_id, {"tenant_id": tenant_id}
        )
        if not isinstance(query, str) or not query:
            raise ValueError("User query must be a non-empty string")
        if not isinstance(response, str) or not response:
            raise ValueError("Assistant response must be a non-empty string")
        if sources is not None and not isinstance(sources, list):
            raise ValueError("Conversation sources must be a list")

        for attempt in range(2):
            db = self.get_db()
            created_session = False
            try:
                session = (db.query(ChatSession)
                           .filter(ChatSession.id == session_id)
                           .with_for_update()
                           .first())
                if session:
                    self._assert_session_owner(session, user_id, tenant_id, visitor_session_id)
                else:
                    created_session = True
                    session = ChatSession(
                        id=session_id,
                        user_id=user_id,
                        tenant_id=tenant_id,
                        visitor_session_id=visitor_session_id,
                        meta={"tenant_id": tenant_id, "user_role": user_role},
                    )
                    db.add(session)

                # The aggregate query flushes a newly-created session before
                # message construction. If another request won the same primary
                # key race, the IntegrityError is caught below and ownership is
                # re-evaluated on the second attempt.
                last_timestamp = (db.query(func.max(ChatMessage.timestamp))
                                  .filter(ChatMessage.session_id == session_id)
                                  .scalar())
                user_timestamp = datetime.now(timezone.utc)
                if last_timestamp is not None:
                    if last_timestamp.tzinfo is None:
                        last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
                    if user_timestamp <= last_timestamp:
                        user_timestamp = last_timestamp + timedelta(microseconds=1)
                assistant_timestamp = user_timestamp + timedelta(microseconds=1)

                user_message_id = str(uuid.uuid4())
                assistant_message_id = str(uuid.uuid4())
                user_message = ChatMessage(
                    id=user_message_id,
                    session_id=session_id,
                    user_id=user_id,
                    message_type="user",
                    content=query,
                    timestamp=user_timestamp,
                    sources=[],
                    meta={"tenant_id": tenant_id},
                )
                assistant_message = ChatMessage(
                    id=assistant_message_id,
                    session_id=session_id,
                    user_id=user_id,
                    message_type="assistant",
                    content=response,
                    timestamp=assistant_timestamp,
                    sources=sources or [],
                    meta={**(assistant_meta or {}), "tenant_id": tenant_id},
                )
                db.add_all([user_message, assistant_message])
                # Derive a conversation title from the first exchange so the
                # history list never shows a blank/untitled session.
                if not session.title:
                    session.title = " ".join(query.split())[:60]
                session.updated_at = assistant_timestamp
                db.commit()
                self._invalidate_chat_history(session_id, user_id, tenant_id, visitor_session_id)
                return {
                    "session_id": session_id,
                    "user_message_id": user_message_id,
                    "assistant_message_id": assistant_message_id,
                }
            except IntegrityError:
                db.rollback()
                if created_session and attempt == 0:
                    continue
                raise
            except Exception:
                db.rollback()
                raise
            finally:
                self.close_db(db)

        raise RuntimeError("Unable to persist chat exchange after ownership race")
    
    def get_chat_history(
        self,
        session_id: str,
        user_id: str,
        tenant_id: str,
        limit: int = 50,
        visitor_session_id: Optional[str] = None,
    ) -> List[ChatMessage]:
        """Get tenant- and user-owned chat history for a session."""
        session_id = self._require_session_id(session_id)
        tenant_id = self._require_ownership(user_id, {"tenant_id": tenant_id})
        # visitor_session_id is folded into the cache key itself (not just the
        # post-fetch ownership check) so a cache HIT can never serve one
        # visitor's cached history to another visitor sharing the same
        # tenant_id+user_id+session_id — see _assert_session_owner's docstring
        # for why that collision is possible in the first place.
        cache_key = f"chat_history:{tenant_id}:{user_id}:{visitor_session_id or ''}:{session_id}:{limit}"

        # Try cache first
        if self.redis:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    for msg in data:
                        if "metadata" in msg and "meta" not in msg:
                            msg["meta"] = msg.pop("metadata")
                    return [ChatMessage(**msg) for msg in data]
            except Exception:
                pass

        # Query database
        db = self.get_db()
        try:
            session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not session:
                raise ConversationNotFoundError("Conversation not found")
            self._assert_session_owner(session, user_id, tenant_id, visitor_session_id)
            messages = db.query(ChatMessage)\
                        .filter(ChatMessage.session_id == session_id)\
                        .order_by(ChatMessage.timestamp.desc())\
                        .limit(limit)\
                        .all()
            
            # Cache result
            if self.redis and messages:
                try:
                    messages_data = []
                    for msg in messages:
                        messages_data.append({
                            "id": msg.id,
                            "session_id": msg.session_id,
                            "user_id": msg.user_id,
                            "message_type": msg.message_type,
                            "content": msg.content,
                            "sources": msg.sources or [],
                            "meta": msg.meta or {}
                        })
                    self.redis.setex(cache_key, 60, json.dumps(messages_data))  # 1 min cache
                except Exception:
                    pass
            
            return messages
        finally:
            self.close_db(db)

    def get_bounded_conversation_context(
        self,
        session_id: str,
        user_id: str,
        tenant_id: str,
        max_messages: int = 10,
        max_chars: int = 4000,
        visitor_session_id: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Return recent, owned messages in chronological order within a hard budget."""
        max_messages = max(0, min(int(max_messages), 20))
        max_chars = max(0, min(int(max_chars), 8000))
        if not max_messages or not max_chars:
            return []

        # get_chat_history applies the authoritative user AND tenant ownership
        # rule and returns newest-first. Build from newest backwards so recent
        # context always wins, then restore chronological prompt order.
        messages = self.get_chat_history(
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            limit=max_messages,
            visitor_session_id=visitor_session_id,
        )
        selected: List[Dict[str, str]] = []
        remaining = max_chars
        for message in messages:
            content = (message.content or "").strip()
            if not content or remaining <= 0:
                continue
            if len(content) > remaining:
                content = content[-remaining:]
            selected.append({"role": message.message_type, "content": content})
            remaining -= len(content)
        selected.reverse()
        return selected
    
    # Session facts management
    def store_session_fact(self, session_id: str, fact_key: str, fact_value: str, 
                          source_document: str = None) -> SessionFact:
        """Store session fact"""
        db = self.get_db()
        try:
            import uuid
            fact = SessionFact(
                id=str(uuid.uuid4()),
                session_id=session_id,
                fact_key=fact_key,
                fact_value=fact_value,
                source_document=source_document
            )
            db.add(fact)
            db.commit()
            db.refresh(fact)
            
            # Invalidate cache
            if self.redis:
                cache_key = f"session_facts:{session_id}"
                self.redis.delete(cache_key)
            
            return fact
        finally:
            self.close_db(db)
    
    def get_session_facts(self, session_id: str) -> Dict[str, Any]:
        """Get all facts for session"""
        cache_key = f"session_facts:{session_id}"
        
        # Try cache first
        if self.redis:
            try:
                cached = self.redis.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception:
                pass
        
        # Query database
        db = self.get_db()
        try:
            facts = db.query(SessionFact)\
                     .filter(SessionFact.session_id == session_id)\
                     .all()
            
            facts_dict = {}
            for fact in facts:
                facts_dict[fact.fact_key] = {
                    "value": fact.fact_value,
                    "source": fact.source_document,
                    "timestamp": fact.created_at.isoformat() if fact.created_at else None
                }
            
            # Cache result
            if self.redis:
                try:
                    self.redis.setex(cache_key, 300, json.dumps(facts_dict))  # 5 min cache
                except Exception:
                    pass
            
            return facts_dict
        finally:
            self.close_db(db)
    
    # Metrics
    def record_metric(self, metric_name: str, metric_value: str, metric_type: str = "gauge"):
        """Record system metric"""
        if not settings.enable_metrics:
            return
        
        db = self.get_db()
        try:
            import uuid
            metric = SystemMetrics(
                id=str(uuid.uuid4()),
                metric_name=metric_name,
                metric_value=str(metric_value),
                metric_type=metric_type
            )
            db.add(metric)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to record metric {metric_name}: {e}")
        finally:
            self.close_db(db)

# Create tables
def create_tables():
    """Create all database tables"""
    try:
        Base.metadata.create_all(bind=engine)
        seed_demo_users()
        seed_bootstrap_documents()
        seed_public_demo_documents()
        if settings.is_production:
            assert_no_committed_credentials()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        raise


def _committed_seed_hashes() -> set:
    from src.config.roles import DEMO_USERS
    return {record["hashed_password"] for record in DEMO_USERS.values()
            if record.get("hashed_password")}


def assert_no_committed_credentials() -> None:
    """Fail closed when an active private account still uses a committed hash.

    The DEMO_USERS password hashes live in source control and their plaintext
    passwords appear in repository documentation, so any private (non
    public-demo) account still carrying one is a publicly known credential.
    Public-demo identities are exempt: they cannot use password login at all
    (see auth.login) and are credentialless by design.
    """
    known = _committed_seed_hashes()
    db = SessionLocal()
    try:
        exposed = [
            row.email for row in db.query(User).filter(
                User.is_active.is_(True),
                User.is_public_demo.is_(False),
            ).all()
            if row.hashed_password in known
        ]
    finally:
        db.close()
    if exposed:
        raise RuntimeError(
            "FATAL: %d active private account(s) still use a password hash committed "
            "to source control (e.g. %s). Reset or deactivate them with "
            "scripts/manage_user.py before starting in production."
            % (len(exposed), exposed[0])
        )


def seed_demo_users() -> None:
    """Idempotently seed demo identities into the authoritative user table.

    Existing rows are deliberately not overwritten: admin changes to roles,
    passwords, tenants, and active state must remain authoritative.

    Production seeds ONLY the public-demo identities. The private sample
    accounts (tenant_acme / tenant_beta admins and staff) have committed
    hashes whose passwords are documented in the repository; seeding them in
    production would ship known administrator credentials. Real production
    accounts are created with scripts/manage_user.py.
    """
    from src.config.roles import DEMO_USERS

    db = SessionLocal()
    try:
        existing = {row[0] for row in db.query(User.email).all() if row[0]}
        for email, record in DEMO_USERS.items():
            normalized = email.strip().lower()
            if normalized in existing:
                continue
            if settings.is_production and not record.get("is_public_demo", False):
                continue
            db.add(User(
                id=normalized,
                username=normalized,
                email=normalized,
                hashed_password=record["hashed_password"],
                full_name=record.get("name") or "User",
                role=(record.get("role") or "employee").lower(),
                tenant_id=record.get("tenant_id"),
                department=record.get("department") or "General",
                is_active=record.get("is_active", True),
                is_public_demo=record.get("is_public_demo", False),
                meta={"seeded_demo_user": True},
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def seed_bootstrap_documents() -> None:
    """Register only explicitly classified bundled files as tenant-owned."""
    from src.config.roles import get_bootstrap_department
    from src.config.settings import get_raw_documents_path

    root = Path(get_raw_documents_path())
    if not root.is_dir():
        return
    db = SessionLocal()
    try:
        known = {row[0] for row in db.query(Document.storage_path).all() if row[0]}
        for path in root.iterdir():
            if not path.is_file() or path.name in known:
                continue
            department = get_bootstrap_department(path.name)
            if department is None:
                continue
            db.add(Document(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"finsolve-bootstrap:{path.name}")),
                filename=path.name,
                tenant_id=settings.bootstrap_tenant_id,
                storage_path=path.name,
                content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                file_size=path.stat().st_size,
                department=department.value,
                uploaded_by="bootstrap",
                processed_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                is_active=True,
                meta={"bootstrap": True},
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def seed_public_demo_documents() -> None:
    """Register immutable, synthetic portfolio documents for ``tenant_demo``."""
    from src.config.roles import get_bootstrap_department
    from src.config.settings import get_demo_documents_path

    root = Path(get_demo_documents_path())
    if not root.is_dir():
        return
    db = SessionLocal()
    try:
        known = {
            row[0] for row in db.query(Document.storage_path).filter(
                Document.tenant_id == settings.demo_tenant_id
            ).all() if row[0]
        }
        for path in root.iterdir():
            if not path.is_file() or path.name in known:
                continue
            department = get_bootstrap_department(path.name)
            if department is None:
                logger.warning("Skipping unclassified public-demo document %s", path.name)
                continue
            db.add(Document(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"finsolve-demo:{path.name}")),
                filename=path.name,
                tenant_id=settings.demo_tenant_id,
                storage_path=path.name,
                content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                file_size=path.stat().st_size,
                department=department.value,
                uploaded_by="public-demo-seed",
                processed_at=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc),
                is_active=True,
                is_protected_demo=True,
                meta={"public_demo_seed": True, "synthetic": True},
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Global database manager instance
db_manager = DatabaseManager()

# Dependency for FastAPI
def get_database():
    """FastAPI dependency for database access"""
    return db_manager
