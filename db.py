from datetime import datetime

from unidecode import unidecode

from sqlalchemy import create_engine, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker, relationship, backref
from sqlalchemy.schema import Column, ForeignKey, Table
from sqlalchemy.types import DateTime, Integer, String, Enum, Text, Boolean, TypeDecorator

import bcrypt

import config

from flask import Flask, url_for
app = Flask('translator')
app.config.from_pyfile("config.py")

if 'mysql' in config.DATABASE:
    engine = create_engine(config.DATABASE, encoding="utf8", pool_size = 100, pool_recycle=4200, echo=config.DEBUG) # XXX
    # pool_recycle is to prevent "server has gone away"
else:
    engine = create_engine(config.DATABASE, encoding="utf8", echo=config.DEBUG)



session = scoped_session(sessionmaker(bind=engine, autoflush=False))

Base = declarative_base(bind=engine)

class WithIdentifier():
    @classmethod
    def from_identifier(cls, identifier, **params):
        return session.query(cls).filter(cls.identifier==identifier).filter_by(**params).scalar()

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, nullable=False)
    username = Column(String(255), nullable=False)
    password = Column(String(255))
    email = Column(String(255))
    minipic_url = Column(String(255), default='')
    profile = Column(Text, default='')
    admin = Column(Boolean, nullable=False, default=False)
    active = Column(Boolean, nullable=False, default=True)
    
    registered = Column(DateTime)
    seen = Column(DateTime)
    
    
    def verify_password(self, password):
        if self.password.startswith('$2b'):
            return bcrypt.hashpw(password.encode('utf-8'), self.password.encode('utf-8')) == self.password.encode('utf-8')
        else:
            raise ValueError("unknown password format")
    
    def set_password(self, password):
        self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    
    @property
    def is_authenticated(self): return True
    
    @property
    def is_active(self): return self.active
    
    @property
    def is_anonymous(self): return False
    
    def get_id(self):
        return str(self.id)
    
    def __str__(self):
        return self.username

class Project(Base, WithIdentifier):
    __tablename__ = 'projects'
    
    id = Column(Integer, primary_key=True, nullable=False)
    identifier = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, default='')
    position = Column(Integer)
    
    categories = relationship("Category", order_by="Category.position")
    
    @property
    def url(self):
        return url_for('index', _anchor=self.identifier)
    
    def __str__(self):
        return self.identifier

class Category(Base, WithIdentifier):
    __tablename__ = 'categories'
    
    id = Column(Integer, primary_key=True, nullable=False)
    identifier = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, default='')
    position = Column(Integer)
    hidden = Column(Boolean, nullable=False, default=False)
    project_id = Column(Integer, ForeignKey('projects.id'))
    
    project = relationship("Project", order_by=position)
    
    @property
    def link_outlinks(self):
        return session.query(Outlink).filter(Outlink.category==self,
            Outlink.type == "link").all()
        
    @property
    def icon(self):
        return session.query(Outlink).filter(Outlink.category==self,
            Outlink.type == "icon").scalar()
    
    @property
    def url(self):
        return url_for('category', 
            project_identifier=self.project.identifier,
            category_identifier=self.identifier)
    
    def count_suggestions(self, rated_by=None):
        suggestion_conditions = (
            Term.category == self,
            Term.locked == False,
            Term.hidden == False,
            Suggestion.status == "approved"
        )
        
        if not rated_by:
            count = session.query(Suggestion).join(Term).filter(
                *suggestion_conditions
            ).count()
        
        else:
            count = session.query("Vote") \
                .select_from(Suggestion) \
                .join("votes") \
                .join(Term) \
                .filter(
                    Vote.user == rated_by,
                    Vote.valid == True,
                    *suggestion_conditions
                ).count()
        
        return count
    
    def __str__(self):
        if self.project:
            return self.project.identifier + '/' + self.identifier
        else:
            return "???" + '/' + self.identifier

class Term(Base, WithIdentifier):
    __tablename__ = 'terms'

    id = Column(Integer, primary_key=True, nullable=False)
    number = Column(Integer)
    identifier = Column(String(255), nullable=False)
    label = Column(String(255))
    text_en = Column(Text)
    text_jp = Column(Text)
    category_id = Column(Integer, ForeignKey('categories.id'))
    hidden = Column(Boolean, default=False, nullable=False)
    locked = Column(Boolean, default=False, nullable=False)
    lock_reason = Column(Text)
    
    category = relationship("Category", backref='terms')
    
    comments = relationship("Comment", order_by="Comment.created")
    
    @property
    def suggestions_w_score(self):
        return session.query(Suggestion, func.sum(Vote.vote).label('score')) \
            .filter(Suggestion.term==self, Suggestion.status == "approved") \
            .outerjoin(Vote).group_by(Suggestion).order_by('score DESC').all()
    
    def user_has_unrated(self, user):
        for suggestion, score in self.suggestions_w_score:
            if not Vote.from_for(user, suggestion):
                return True
        return False
    
    @property
    def prev(self):
        return session.query(Term).filter(Term.category == self.category) \
            .filter(Term.number < self.number) \
            .order_by(Term.number.desc()).first()
            
    @property
    def next(self):
        return session.query(Term).filter(Term.category == self.category) \
            .filter(Term.number > self.number) \
            .order_by(Term.number.asc()).first()
    
    def __str__(self):
        if self.category:
            return str(self.category) \
                + "/" + self.identifier
        else:
            return "???" \
                + "/" + self.identifier
    
    @property
    def url(self):
        return url_for('term', 
            project_identifier=self.category.project.identifier,
            category_identifier=self.category.identifier,
            term_identifier=self.identifier)

class Suggestion(Base):
    __tablename__ = 'suggestions'
    
    id = Column(Integer, primary_key=True, nullable=False)
    text = Column(Text)
    description = Column(Text, default='')
    status = Column(Enum("new", "denied", "approved", "withdrawn", "final", "hidden", "deleted"))
    
    created = Column(DateTime)
    changed = Column(DateTime)
    
    term_id = Column(Integer, ForeignKey('terms.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    
    term = relationship("Term", backref='suggestions')
    user = relationship("User", backref='suggestions')
    
    @property
    def score(self):
        score = session.query(
            func.sum(Vote.vote).label('score')).filter(
            Vote.suggestion == self and Vote.valid == True).scalar() or 0
        return score
    
    @property
    def negative_score(self):
        score = session.query(Vote).filter(
            Vote.suggestion == self and Vote.valid == True,
            Vote.vote == 0).count() or 0
        return score
    
    @property
    def url(self):
        return self.term.url

class Comment(Base):
    __tablename__ = 'comments'
    
    id = Column(Integer, primary_key=True, nullable=False)
    text = Column(Text)
    created = Column(DateTime)
    deleted = Column(Boolean)
    
    term_id = Column(Integer, ForeignKey('terms.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    
    term = relationship("Term")
    user = relationship("User", backref='comments')

class Vote(Base):
    __tablename__ = 'votes'
    
    suggestion_id = Column(Integer, ForeignKey('suggestions.id'), primary_key=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True, nullable=False)
    vote = Column(Integer, nullable=False)
    valid = Column(Boolean)
    
    suggestion = relationship("Suggestion", backref='votes')
    user = relationship("User", backref='votes')
    
    changed = Column(DateTime)
    
    @classmethod
    def from_for(cls, user, suggestion):
        return session.query(cls).filter(cls.user == user,
            cls.suggestion == suggestion).scalar()
    
class Outlink(Base):
    __tablename__ = 'outlinks'
    id = Column(Integer, primary_key=True, nullable=False)
    label = Column(String(255))
    url = Column(String(255))
    category_id = Column(Integer, ForeignKey('categories.id'))
    type = Column(Enum("link", "image", "icon"))
    
    category = relationship("Category", backref='outlinks')
    
    def filled_url(self, term):
        return self.url.format(**{
            'term': term.text_en,
            'en': term.text_en,
            'en_lower': term.text_en.lower(),
            'en_lowercase': term.text_en.lower(),
            'en_capitalized': term.text_en.capitalize(),
            'en_title': term.text_en.title(),
            'jp': term.text_jp,
            'num': term.number,
            'number': term.number})
    
    def __str__(self):
        return "{}/{} {}".format(self.category, self.type, self.label)
    

if __name__ == '__main__':
    Base.metadata.create_all(bind=engine)


















