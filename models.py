# models.py — All SQLAlchemy models for Preferendum

from sqlalchemy import (
    Column, Integer, String, Text, DateTime,
    ForeignKey, Boolean, Float
)
from sqlalchemy.orm import relationship
from datetime import datetime
from db import Base


class User(Base):
    """Registered voter. Identity data — NEVER linked to vote records."""
    __tablename__ = "users"

    id          = Column(Integer, primary_key=True, index=True)
    email       = Column(String, unique=True, index=True, nullable=False)
    name        = Column(String, nullable=False)
    password    = Column(String, nullable=False)          # bcrypt hash
    role        = Column(String, default="voter")         # voter / organizer / admin
    country     = Column(String)
    state       = Column(String)
    county      = Column(String)
    dob         = Column(String)                          # ISO date YYYY-MM-DD
    gender      = Column(String)                          # F / M / O
    national_id = Column(String, unique=True)             # RUT, DNI, etc.
    phone       = Column(String, unique=True)
    imei        = Column(String, unique=True)
    is_verified = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=datetime.utcnow)

    votes    = relationship("AnonymousVoteRecord", back_populates="nothing", foreign_keys=[])
    comments = relationship("DebateComment", back_populates="user")


class Debate(Base):
    """A debate/question created by an institution."""
    __tablename__ = "debates"

    id           = Column(Integer, primary_key=True, index=True)
    title        = Column(String, nullable=False)
    description  = Column(Text, nullable=False)
    category     = Column(String)
    institution  = Column(String)
    inst_type    = Column(String, default="gov")          # gov / priv / union / ngo
    country      = Column(String)
    state        = Column(String)
    county       = Column(String)
    min_age      = Column(Integer)
    max_age      = Column(Integer)
    gender       = Column(String, default="all")
    start_dt     = Column(DateTime, default=datetime.utcnow)
    end_dt       = Column(DateTime)
    is_closed    = Column(Boolean, default=False)
    is_closed_list = Column(Boolean, default=False)       # members-only
    follow_up_questions = Column(Text, default='')        # JSON: branching Q2/Q3 tree per Q1 option

    options  = relationship("DebateOption", back_populates="debate", cascade="all,delete")
    comments = relationship("DebateComment", back_populates="debate", cascade="all,delete")
    votes    = relationship("AnonymousVoteRecord", back_populates="debate", cascade="all,delete")


class DebateOption(Base):
    """One voting option within a debate."""
    __tablename__ = "debate_options"

    id        = Column(Integer, primary_key=True, index=True)
    debate_id = Column(Integer, ForeignKey("debates.id"))
    text      = Column(String, nullable=False)
    order_num = Column(Integer, default=0)

    debate = relationship("Debate", back_populates="options")


class DebateComment(Base):
    """A comment posted in a debate's discussion feed."""
    __tablename__ = "debate_comments"

    id         = Column(Integer, primary_key=True, index=True)
    debate_id  = Column(Integer, ForeignKey("debates.id"))
    user_id    = Column(Integer, ForeignKey("users.id"))
    content    = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    likes      = Column(Integer, default=0)
    dislikes   = Column(Integer, default=0)

    debate = relationship("Debate", back_populates="comments")
    user   = relationship("User", back_populates="comments")


class AnonymousVoteRecord(Base):
    """
    THE VOTE RECORD — zero identity.
    Bridge destroyed: voter_id is NEVER stored here.
    Only anonymous demographics + encrypted vote.
    """
    __tablename__ = "anonymous_vote_records"

    id             = Column(Integer, primary_key=True, index=True)
    debate_id      = Column(Integer, ForeignKey("debates.id"))
    encrypted_vote = Column(Text, nullable=False)         # AES-256 encrypted
    vote_hash      = Column(String, nullable=False)       # SHA-256 of encrypted
    tx_hash        = Column(String)                       # Polygon blockchain tx
    vcode          = Column(String, unique=True)          # Voter's verification code

    vote_chain = Column(Text, default='[]')               # JSON: full Q1→Q2→Q3 answer path

    # Anonymous demographics only
    gender     = Column(String)                           # F / M / O
    age_group  = Column(String)                           # 18-24, 25-34, etc.
    county     = Column(String)
    country    = Column(String)

    created_at = Column(DateTime, default=datetime.utcnow)

    debate = relationship("Debate", back_populates="votes")
    # NO user relationship — bridge is destroyed


class HasVotedLog(Base):
    """
    Duplicate-vote prevention ONLY.
    Maps user_id → debate_id to block double-voting.
    Contains NO vote data — only the fact that a vote was cast.
    """
    __tablename__ = "has_voted_log"

    id        = Column(Integer, primary_key=True, index=True)
    user_id   = Column(Integer, ForeignKey("users.id"), nullable=False)
    debate_id = Column(Integer, ForeignKey("debates.id"), nullable=False)
    voted_at  = Column(DateTime, default=datetime.utcnow)


class AdCampaign(Base):
    """An advertising campaign created by an institution."""
    __tablename__ = "ad_campaigns"

    id               = Column(Integer, primary_key=True, index=True)
    advertiser_email = Column(String, nullable=False)
    advertiser_name  = Column(String)
    title            = Column(String, nullable=False)
    ad_type          = Column(String, default="banner")   # banner / text / video / question
    budget_clp       = Column(Integer, default=0)
    spent_clp        = Column(Integer, default=0)
    cost_per_view    = Column(Integer, default=20)        # CLP per impression

    # Targeting
    target_country   = Column(String)
    target_regions   = Column(String)                     # comma-separated
    target_communes  = Column(String)
    target_gender    = Column(String, default="all")
    target_age_ranges= Column(String)                     # e.g. "18-24,25-34"
    target_categories= Column(String)                     # debate categories
    excluded_categories = Column(String)
    blocked_competitors = Column(String)

    # Creative
    banner_path      = Column(String)
    ad_text          = Column(Text)

    start_date       = Column(DateTime)
    end_date         = Column(DateTime)
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime, default=datetime.utcnow)

    impressions = relationship("AdImpressionLog", back_populates="campaign", cascade="all,delete")


class AdImpressionLog(Base):
    """One impression = one voter saw one ad."""
    __tablename__ = "ad_impression_logs"

    id          = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("ad_campaigns.id"))
    debate_id   = Column(Integer, ForeignKey("debates.id"))
    gender      = Column(String)
    age_group   = Column(String)
    county      = Column(String)
    country     = Column(String)
    viewed_at   = Column(DateTime, default=datetime.utcnow)

    campaign = relationship("AdCampaign", back_populates="impressions")


class VoteVerificationLog(Base):
    """Public verification record — voter can check their code."""
    __tablename__ = "vote_verification_logs"

    id        = Column(Integer, primary_key=True, index=True)
    vcode     = Column(String, unique=True, index=True)
    vote_hash = Column(String, nullable=False)
    tx_hash   = Column(String)
    debate_id = Column(Integer)
    verified_at = Column(DateTime, default=datetime.utcnow)
