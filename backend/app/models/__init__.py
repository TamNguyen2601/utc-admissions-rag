"""Registered domain models."""

from app.models.identity import AuthSession, User
from app.models.knowledge import DataSource, Document, DocumentOrigin, DocumentChunk
from app.models.crawl import CrawlRun, CrawlRunItem
from app.models.conversation import Conversation, Message
from app.models.career import JobPosting
from app.models.quiz import Major, QuizQuestion

__all__ = ["AuthSession", "User", "DataSource", "Document", "DocumentOrigin", "DocumentChunk", "CrawlRun", "CrawlRunItem", "Conversation", "Message", "JobPosting", "Major", "QuizQuestion"]
