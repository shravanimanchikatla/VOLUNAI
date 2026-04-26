from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='volunteer') # 'volunteer' or 'organizer'
    location = db.Column(db.String(100), nullable=True) # Zip code or city
    skills = db.Column(db.String(255), nullable=True) # Comma separated list of skills
    is_available = db.Column(db.Boolean, default=False)
    
    # Relationship to tasks they've accepted
    tasks = db.relationship('Task', backref='volunteer', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    raw_text = db.Column(db.Text, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Cascade delete reports when an organizer is deleted
    organizer = db.relationship('User', backref=db.backref('reports', lazy=True, cascade="all, delete-orphan"))
    # Cascade delete tasks when a report is deleted
    tasks = db.relationship('Task', backref='report', lazy=True, cascade="all, delete-orphan")

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('report.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    required_skills = db.Column(db.String(255), nullable=False)
    location = db.Column(db.String(100), nullable=False)
    urgency_score = db.Column(db.Integer, nullable=False) # 1-10
    status = db.Column(db.String(20), default='open') # 'open', 'assigned', 'completed'
    assigned_volunteer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
