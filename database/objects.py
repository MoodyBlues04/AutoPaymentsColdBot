from typing import Any, Dict

from sqlalchemy import Boolean, Column, Integer, String, create_engine, Float, BigInteger
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

engine = create_engine("postgresql+psycopg2://admin:rL1XSezBGxye7A4m@localhost")
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)
Base = declarative_base()


class Payments(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    from_wallet = Column(String)
    wallet = Column(String)
    amount = Column(Float)
    payment_timestamp = Column(Integer)
    every_month = Column(Integer, default=0)
    status = Column(Integer, default=1)

    def to_json(self) -> Dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Users(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer)
    user_id = Column(BigInteger)
    action = Column(String, nullable=False)
