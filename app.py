import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, redirect, url_for, flash, session
import os
import json
from dotenv import load_dotenv
from models import db, User, Task, Report
from flask_socketio import SocketIO, emit, join_room

# Load environment variables
load_dotenv(override=True)

app = Flask(__name__, 
            template_folder='templates',
            static_folder='static')
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default-dev-key')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

@socketio.on('join')
def on_join(data):
    user_id = data.get('user_id')
    if user_id:
        join_room(f"user_{user_id}")
        print(f"User {user_id} joined their private room.")

# Database Configuration
db_url = os.getenv('DATABASE_URL')
if db_url:
    # Ensure it uses pymysql driver
    if db_url.startswith('mysql://'):
        db_url = db_url.replace('mysql://', 'mysql+pymysql://', 1)
    
    # Remove incompatible ssl-mode argument if present (common in Aiven URIs)
    if 'ssl-mode=' in db_url:
        import re
        db_url = re.sub(r'[?&]ssl-mode=[^&]*', '', db_url)
    
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    
    # Explicit SSL support for Aiven/Cloud DBs
    if "aivencloud.com" in db_url:
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            "connect_args": {
                "ssl": {
                    "ssl_mode": "REQUIRED"
                }
            },
            "pool_pre_ping": True
        }
else:
    db_user = os.getenv('DB_USERNAME', 'root')
    db_pass = os.getenv('DB_PASSWORD', 'password')
    db_host = os.getenv('DB_HOST', 'localhost')
    db_name = os.getenv('DB_NAME', 'smart_volunteer_db')
    import urllib.parse
    db_pass_encoded = urllib.parse.quote_plus(db_pass)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{db_user}:{db_pass_encoded}@{db_host}/{db_name}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

db.init_app(app)

# Create tables if they don't exist
with app.app_context():
    db.create_all()

# Simple route for testing the base setup
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')
        skills = request.form.get('skills', '')

        if not email.endswith('@gmail.com'):
            flash('Only @gmail.com addresses are allowed.')
            return redirect(url_for('signup'))

        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email address already exists')
            return redirect(url_for('signup'))

        new_user = User(name=name, email=email, role=role, skills=skills)
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            session['user_role'] = user.role

            if user.role == 'organizer':
                return redirect(url_for('organizer_dashboard'))
            else:
                return redirect(url_for('volunteer_dashboard'))
        else:
            flash('Invalid email or password')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        flash(f'A password reset link has been sent to {email}')
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        user.name = request.form.get('name')
        user.location = request.form.get('location')
        if user.role == 'volunteer':
            user.skills = request.form.get('skills')
            user.is_available = 'is_available' in request.form
            
        db.session.commit()
        flash("Profile updated successfully!")
        return redirect(url_for('profile'))
        
    return render_template('profile.html', user=user)

def get_user_points(user_id):
    completed_tasks = Task.query.filter_by(assigned_volunteer_id=user_id, status='completed').all()
    return sum([t.urgency_score for t in completed_tasks])

def auto_assign_task(task):
    print(f"DEBUG: Attempting auto-assign for task '{task.title}' at location '{task.location}'")
    # Find all available volunteers
    all_available = User.query.filter_by(role='volunteer', is_available=True).all()
    
    # Match by stripped, case-insensitive location
    target_loc = task.location.strip().lower()
    available_volunteers = [v for v in all_available if v.location and v.location.strip().lower() == target_loc]
    
    print(f"DEBUG: Scanned {len(all_available)} available volunteers. Found {len(available_volunteers)} matches for '{target_loc}'")
    
    if not available_volunteers:
        return None
        
    # Sort by points (highest first)
    best_volunteer = sorted(available_volunteers, key=lambda v: get_user_points(v.id), reverse=True)[0]
    
    print(f"DEBUG: Assigning task to {best_volunteer.name} (ID: {best_volunteer.id})")
    
    # Assign the task
    task.assigned_volunteer_id = best_volunteer.id
    task.status = 'assigned'
    db.session.commit()

    # Emit real-time notification to the volunteer
    print(f"DEBUG: Emitting 'new_assignment' to room 'user_{best_volunteer.id}'")
    socketio.emit('new_assignment', {
        'title': task.title,
        'location': task.location,
        'urgency': task.urgency_score
    }, room=f"user_{best_volunteer.id}")

    return best_volunteer

@app.route('/delete_account', methods=['POST'])
def delete_account():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user = User.query.get(session['user_id'])
    if user:
        # Re-assign their active tasks or let cascade handle it. Let's just drop them.
        db.session.delete(user)
        db.session.commit()
        session.clear()
        flash('Your account has been permanently deleted.')
        
    return redirect(url_for('index'))

@app.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    if 'user_id' not in session or session.get('user_role') != 'organizer':
        return redirect(url_for('login'))
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()
    flash("Task deleted successfully.")
    return redirect(url_for('organizer_view_tasks'))

@app.route('/unassign_task/<int:task_id>', methods=['POST'])
def unassign_task(task_id):
    if 'user_id' not in session or session.get('user_role') != 'organizer':
        return redirect(url_for('login'))
    task = Task.query.get_or_404(task_id)
    task.assigned_volunteer_id = None
    task.status = 'open'
    db.session.commit()
    flash("Task unassigned and returned to the open pool.")
    return redirect(url_for('organizer_view_tasks'))

@app.route('/release_task/<int:task_id>', methods=['POST'])
def release_task(task_id):
    if 'user_id' not in session or session.get('user_role') != 'volunteer':
        return redirect(url_for('login'))
    task = Task.query.get_or_404(task_id)
    if task.assigned_volunteer_id == session['user_id']:
        task.assigned_volunteer_id = None
        task.status = 'open'
        db.session.commit()
        flash("You have released the task.")
    return redirect(url_for('volunteer_dashboard'))

@app.route('/bulk_delete_completed', methods=['POST'])
def bulk_delete_completed():
    if 'user_id' not in session or session.get('user_role') != 'organizer':
        return redirect(url_for('login'))
    Task.query.filter_by(status='completed').delete()
    db.session.commit()
    flash("All completed tasks have been cleaned up.")
    return redirect(url_for('organizer_view_tasks'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

import google.generativeai as genai
import json
import pandas as pd
import PyPDF2
from werkzeug.utils import secure_filename

def extract_text_from_file(file):
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    try:
        if ext == 'txt':
            return file.read().decode('utf-8')
        elif ext == 'csv':
            df = pd.read_csv(file)
            return df.to_string()
        elif ext in ['xls', 'xlsx']:
            df = pd.read_excel(file)
            return df.to_string()
        elif ext == 'pdf':
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
    except Exception as e:
        print(f"Error parsing file: {e}")
    return None

@app.route('/organizer')
def organizer_dashboard():
    if 'user_id' not in session or session.get('user_role') != 'organizer':
        return redirect(url_for('login'))
    
    briefing = session.pop('ai_briefing', None)
    return render_template('organizer_dashboard.html', briefing=briefing)

@app.route('/volunteer')
def volunteer_dashboard():
    if 'user_id' not in session or session.get('user_role') != 'volunteer':
        return redirect(url_for('login'))
        
    user = User.query.get(session['user_id'])
    user_skills = [s.strip().lower() for s in (user.skills or "").split(',') if s.strip()]
    
    my_tasks = Task.query.filter_by(assigned_volunteer_id=user.id).all()
    all_open = Task.query.filter_by(status='open').order_by(Task.urgency_score.desc()).all()
    
    matched_tasks = []
    other_tasks = []
    
    for task in all_open:
        task_skills = [s.strip().lower() for s in (task.required_skills or "").split(',') if s.strip()]
        
        is_match = False
        if "any" in task_skills:
            is_match = True
        else:
            for s in user_skills:
                for ts in task_skills:
                    if s in ts or ts in s:
                        is_match = True
                        break
                if is_match:
                    break
                    
        if is_match or not user_skills: 
            matched_tasks.append(task)
        else:
            other_tasks.append(task)
            
    return render_template('volunteer_dashboard.html', my_tasks=my_tasks, matched_tasks=matched_tasks, other_tasks=other_tasks)

@app.route('/accept_task/<int:task_id>', methods=['POST'])
def accept_task(task_id):
    if 'user_id' not in session or session.get('user_role') != 'volunteer':
        return redirect(url_for('login'))
        
    task = Task.query.get_or_404(task_id)
    if task.status == 'open':
        task.status = 'assigned'
        task.assigned_volunteer_id = session['user_id']
        db.session.commit()
        flash("Task accepted successfully! Please proceed to the location.")
    else:
        flash("Sorry, this task has already been assigned or completed.")
        
    return redirect(url_for('volunteer_dashboard'))

@app.route('/organizer/tasks')
def organizer_view_tasks():
    if 'user_id' not in session or session.get('user_role') != 'organizer':
        return redirect(url_for('login'))
        
    tasks = Task.query.order_by(Task.created_at.desc()).all()
    return render_template('organizer_view_tasks.html', tasks=tasks)

@app.route('/complete_task/<int:task_id>', methods=['POST'])
def complete_task(task_id):
    if 'user_id' not in session or session.get('user_role') != 'volunteer':
        return redirect(url_for('login'))
        
    task = Task.query.get_or_404(task_id)
    if task.assigned_volunteer_id == session['user_id'] and task.status != 'completed':
        task.status = 'completed'
        db.session.commit()
        flash("Incredible work! You have successfully completed the task.")
    else:
        flash("You cannot complete this task.")
        
    return redirect(url_for('volunteer_dashboard'))

@app.route('/organizer/roster')
def organizer_roster():
    if 'user_id' not in session or session.get('user_role') != 'organizer':
        return redirect(url_for('login'))
        
    volunteers = User.query.filter_by(role='volunteer').order_by(User.id.desc()).all()
    return render_template('organizer_roster.html', volunteers=volunteers)

@app.route('/leaderboard')
def leaderboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    volunteers = User.query.filter_by(role='volunteer').all()
    leaderboard_data = []
    
    for vol in volunteers:
        completed_tasks = Task.query.filter_by(assigned_volunteer_id=vol.id, status='completed').all()
        points = sum([t.urgency_score for t in completed_tasks])
        if points > 0:
            leaderboard_data.append({
                'name': vol.name,
                'skills': vol.skills,
                'tasks_completed': len(completed_tasks),
                'points': points
            })
            
    leaderboard_data = sorted(leaderboard_data, key=lambda x: x['points'], reverse=True)
    return render_template('leaderboard.html', leaderboard=leaderboard_data)

@app.route('/generate_briefing')
def generate_briefing():
    if 'user_id' not in session or session.get('user_role') != 'organizer':
        return redirect(url_for('login'))
        
    open_tasks = Task.query.filter_by(status='open').all()
    if not open_tasks:
        flash("There are no open tasks to analyze.")
        return redirect(url_for('organizer_dashboard'))
        
    task_descriptions = [f"- {t.title} at {t.location} (Urgency: {t.urgency_score}, Skills: {t.required_skills})" for t in open_tasks]
    task_text = "\n".join(task_descriptions)
    
    try:
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        You are an AI crisis management assistant. Below is a list of all currently open emergency tasks in the city.
        Please write a 2-3 paragraph "Situation Report" summarizing the biggest threats, what skills are most needed right now, and any geographical hotspots.
        Do not output JSON. Just output a clean, professional text summary.
        
        Open Tasks:
        {task_text}
        """
        response = model.generate_content(prompt)
        session['ai_briefing'] = response.text.strip()
    except Exception as e:
        print(f"Error calling Gemini for briefing: {e}")
        flash("Error generating AI briefing.")
        
    return redirect(url_for('organizer_dashboard'))

@app.route('/submit_report', methods=['POST'])
def submit_report():
    if 'user_id' not in session or session.get('user_role') != 'organizer':
        return redirect(url_for('login'))
        
    raw_text = request.form.get('raw_text', '')
    
    file = request.files.get('report_file')
    if file and file.filename != '':
        extracted_text = extract_text_from_file(file)
        if extracted_text is None:
            flash("Unsupported or corrupted file format. Please upload TXT, CSV, XLSX, or PDF.")
            return redirect(url_for('organizer_dashboard'))
        raw_text += "\n\n--- Extracted from File ---\n" + extracted_text
        
    if not raw_text.strip():
        flash("Please provide either text or upload a file.")
        return redirect(url_for('organizer_dashboard'))
    
    report = Report(organizer_id=session['user_id'], raw_text=raw_text)
    db.session.add(report)
    db.session.flush()
    
    try:
        api_key = os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        Analyze the following raw field report data. It may contain one or multiple separate emergency events.
        Extract EACH distinct problem into a separate task.
        Output ONLY a valid JSON ARRAY of objects. Even if there is only one task, put it in an array.
        Format:
        [
            {{
                "title": "A short 3-5 word title",
                "description": "A clear 1-2 sentence description of the problem",
                "location": "The location mentioned (or 'Unknown' if not specified)",
                "required_skills": "A single word or short phrase for the main skill needed (e.g. 'Carpentry', 'Medical', 'General Labor')",
                "urgency_score": an integer from 1 to 10 (10 being life-threatening emergency, 1 being not urgent)
            }}
        ]
        
        Report Data:
        {raw_text}
        """
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        if text.startswith("```json"):
            text = text[7:-3]
        elif text.startswith("```"):
            text = text[3:-3]
            
        tasks_data = json.loads(text)
        
        if not isinstance(tasks_data, list):
            tasks_data = [tasks_data]
            
        for data in tasks_data:
            task = Task(
                report_id=report.id,
                title=data.get('title', 'Extracted Task'),
                description=data.get('description', 'No description available'),
                location=data.get('location', 'Unknown'),
                required_skills=data.get('required_skills', 'Any'),
                urgency_score=data.get('urgency_score', 5)
            )
            db.session.add(task)
            db.session.commit()
            
            # Trigger Auto-Assignment
            auto_assign_task(task)
            
        flash(f"Successfully processed reports! {len(tasks_data)} tasks created.")
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        db.session.rollback()
        flash("Error analyzing report. Please ensure your Gemini API key is set in .env")
        
    return redirect(url_for('organizer_dashboard'))

if __name__ == '__main__':
    socketio.run(app, debug=True, allow_unsafe_werkzeug=True)
