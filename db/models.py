from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, create_engine, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
import datetime
import enum
import calendar

Base = declarative_base()

class UserRole(enum.Enum):
    USER = "user"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.USER)
    port = Column(Integer, unique=True, nullable=False)
    login = Column(String, nullable=False)
    timezone = Column(String, default='UTC')
    subscription_until = Column(DateTime, nullable=False)
    
    modes = relationship("Mode", back_populates="user", cascade="all, delete-orphan")
    schedules = relationship("Schedule", back_populates="user", cascade="all, delete-orphan")
    payment_requests = relationship("PaymentRequest", back_populates="user", cascade="all, delete-orphan")
    
    def is_subscription_active(self):
        return datetime.datetime.now() <= self.subscription_until
    
    def __repr__(self):
        return f"<User(id={self.id}, tg_id={self.tg_id}, username={self.username}, port={self.port})>"

class Mode(Base):
    __tablename__ = 'modes'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    name = Column(String, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    alias = Column(String, nullable=False)
    is_active = Column(Integer, default=0)  # 0 - неактивный, 1 - активный
    
    user = relationship("User", back_populates="modes")
    schedules = relationship("Schedule", back_populates="mode", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Mode(id={self.id}, name={self.name}, host={self.host}, port={self.port})>"

class Schedule(Base):
    __tablename__ = 'schedules'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    mode_id = Column(Integer, ForeignKey('modes.id'), nullable=False)
    start_time = Column(String, nullable=False)  # Формат "HH:MM"
    end_time = Column(String, nullable=False)    # Формат "HH:MM"
    
    user = relationship("User", back_populates="schedules")
    mode = relationship("Mode", back_populates="schedules")
    
    def __repr__(self):
        return f"<Schedule(id={self.id}, mode_id={self.mode_id}, start_time={self.start_time}, end_time={self.end_time})>"

class PaymentMethod(enum.Enum):
    BEP20 = "bep20"
    TRC20 = "trc20"
    CARD = "card"

class PaymentStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class PaymentRequest(Base):
    __tablename__ = 'payment_requests'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    method = Column(Enum(PaymentMethod), nullable=False)
    file_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.PENDING)

    user = relationship("User", back_populates="payment_requests")

def init_db(db_url=None):
    """Инициализация базы данных"""
    # Если URL базы не передан, используем значение из настроек
    if db_url is None:
        try:
            from config.settings import (
                DATABASE_URL,
                DB_POOL_SIZE,
                DB_MAX_OVERFLOW,
                DB_POOL_TIMEOUT,
                DB_POOL_RECYCLE,
                DB_POOL_PRE_PING,
            )
            db_url = DATABASE_URL
        except Exception:
            # Фолбэк на локальную SQLite, если настройки недоступны
            db_url = "sqlite:///stratum_proxy.db"
            DB_POOL_SIZE = 200
            DB_MAX_OVERFLOW = 400
            DB_POOL_TIMEOUT = 60
            DB_POOL_RECYCLE = 1800
            DB_POOL_PRE_PING = True
    engine = create_engine(
        db_url,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT,
        pool_pre_ping=DB_POOL_PRE_PING,
        pool_recycle=DB_POOL_RECYCLE,
    )
    Base.metadata.create_all(engine)
    return engine

def get_session(engine):
    """Создание сессии для работы с базой данных"""
    Session = sessionmaker(bind=engine)
    return Session()