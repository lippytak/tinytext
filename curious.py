import os, re
import logging
from logging.handlers import RotatingFileHandler
from threading import Thread
from twilio.rest import TwilioRestClient
from datetime import datetime, date
from flask import Flask, flash, request, Response, render_template, redirect, url_for
from flask.ext.login import LoginManager, login_user, logout_user, current_user, login_required
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy import desc
from wtforms import Form, TextField, TextAreaField, validators

# Config
app = Flask(__name__)
app.config['DEBUG'] = os.environ['DEBUG']
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
app.secret_key = os.environ['SECRET_KEY']
db = SQLAlchemy(app)
lm = LoginManager()
lm.init_app(app)

# Logging
handler = RotatingFileHandler('log.log', maxBytes=10000, backupCount=1)
handler.setLevel(logging.INFO)
app.logger.addHandler(handler)

# Views
@lm.user_loader
def load_user(id):
  return User.query.get(int(id)) if id != 'None' else None

@lm.unauthorized_handler
def unauthorized():
  # flash('Woh! Eeeeeeep')
  return redirect(url_for("login"))

@app.errorhandler(404)
def not_found(error):
    return render_template('error.html'), 404

@app.teardown_request
def shutdown_session(exception=None):
  try:
    db.session.commit()
    db.session.remove()
  except:
    db.session.rollback()

@app.route("/login", methods=["GET", "POST"])
def login():
  if current_user.is_authenticated():
    return redirect(url_for("index"))
  
  # GET > render form
  if request.method == 'GET':
    return render_template('login.html')

  # POST > process form and send to index
  form = LoginForm(request.form)
  if request.method == 'POST' and form.validate():
    user = form.get_user()
    login_user(user)
    # flash("Welcome back!")
  elif request.method == 'POST' and not form.validate():
    flash("I don't see an account with that phone #. Maybe try creating a new one?")
  return redirect(url_for("index"))

@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegistrationForm(request.form)
    if request.method == 'POST' and form.validate():
      u = User(raw_phone_number = form.phone_number.data,
              org_nickname = form.org_nickname.data)
      db.session.add(u)
      db.session.commit()
      send_message(u.normalized_phone_number, render_template('welcome-user.html'))
      login_user(u)
      flash("Welcome! Glad to have you. Start by adding some peeps to answer your questions.")
    return redirect(url_for("clients"))

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))

@app.route('/')
def index():
  '''Renders either login page or org home page or client page'''
  if current_user.is_authenticated():
    if current_user.clients:
      form = QuestionForm(request.form)
      return render_template('index.html',
          form = form,
          user = current_user)
    else:
      flash('Great! Start by adding some peeps so you can ask them questions.')
      return redirect(url_for('clients'))
  else:
    return render_template('login.html')

@app.route("/<org_url>")
def org(org_url):
  '''Public org landing page'''
  user = User.query.filter_by(org_url = org_url).first()
  if user:
    return render_template('org.html', user = user)
  return redirect(url_for("index"))

@app.route('/sms')
def sms():
  # get client
  from_number = normalize_phone_number(request.values.get('From'))
  msg = request.values.get('Body')
  c, status = get_or_create_client(from_number)

  if status == 'new':
    send_message(c.normalized_phone_number, render_template('welcome.html'))
    return 'welcomed new client'

  # check for joining keyword
  if msg[0] == '#':
    u = find_user_by_keyword_msg(msg)
    if u:
      u.clients.append(c)
      db.session.add(u)
      send_message(c.normalized_phone_number, render_template('welcome.html'))
      return 'client joined org'
    else:
      send_message(c.normalized_phone_number, render_template('invalid-keyword.html'))
      return 'invalid keyword'
  
  # get last q
  q = c.get_last_question()

  # create answer
  a = Answer(text = msg)

  # save + commit everything
  q.answers.append(a)
  c.answers.append(a)
  db.session.add_all([c, q, a])
  db.session.commit()
  return 'saved answer to most recent question'

@app.route('/q/<q_id>')
def question(q_id):
  q = Question.query.get(q_id)
  return render_template('question.html', question = q)

@app.route('/peeps', methods=['GET', 'POST'])
@login_required
def clients():
  form = ImportForm(request.form)
  success_count = 0
  if request.method == 'POST' and form.validate():
    phone_numbers = parse_phone_numbers(form.phone_numbers.data)
    for p in phone_numbers:
      try:
        c, status = get_or_create_client(p)
        current_user.clients.append(c)
        db.session.add(c)
        success_count += 1
      except Exception:
        pass
    flash('''Perfect, you just added %s new peeps.
          Now ask them something interesting!''' % success_count)
    return redirect(url_for('index'))
  return render_template('clients.html', user = current_user)

@app.route('/peeps/remove/<int:id>')
@login_required
def remove_client(id):
  c = Client.query.get(id)
  current_user.remove_client(c)
  return redirect(url_for('clients'))

@app.route('/question', methods=['POST'])
def ask_question():
  form = QuestionForm(request.form)
  if request.method == 'POST' and form.validate():
      q = Question(form.question_text.data)
      db.session.add(q)
      current_user.send_question(q)
      flash('Great question. Now be patient for responses.')
  return redirect(url_for('index'))

@app.route('/q/<q_id>/answers.csv')
def generate_answers_csv(q_id):
  answers = Question.query.get(q_id).answers
  csv = ''
  for a in answers:
    csv += '%s, %s \n' % (a.client.normalized_phone_number, a.text)
  return Response(csv, mimetype='text/csv')

# Models
user_clients = db.Table('user_clients',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('client_id', db.Integer, db.ForeignKey('client.id'))
)

client_questions = db.Table('client_questions',
    db.Column('client_id', db.Integer, db.ForeignKey('client.id')),
    db.Column('question_id', db.Integer, db.ForeignKey('question.id'))
)

class Client(db.Model):
  '''Clients receive questions and answer them'''
  id = db.Column(db.Integer, primary_key=True)
  normalized_phone_number = db.Column(db.String(20), unique=True)
  raw_phone_number = db.Column(db.String(50))
  answers = db.relationship('Answer', backref='client', lazy='dynamic')
  questions = db.relationship('Question',
              secondary=client_questions,
              backref=db.backref('clients', lazy='dynamic'))

  def __init__(self, raw_phone_number):
    self.raw_phone_number = raw_phone_number
    self.normalized_phone_number = normalize_phone_number(raw_phone_number)

  def get_last_question(self):
    # TODO sort on timestamp
    return self.questions[-1]

class Question(db.Model):
  '''Questions are sent to clients and have answers'''
  id = db.Column(db.Integer, primary_key=True)
  user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
  timestamp = db.Column(db.DateTime)
  text = db.Column(db.String)
  answers = db.relationship('Answer', backref='question', lazy='dynamic')
  
  def __init__(self, text, timestamp = None):
    self.text = text
    if timestamp is None:
      self.timestamp = datetime.utcnow()

class Answer(db.Model):
  '''Clients send answers to questions'''
  id = db.Column(db.Integer, primary_key=True)
  timestamp = db.Column(db.DateTime)
  text = db.Column(db.String)
  question_id = db.Column(db.Integer, db.ForeignKey('question.id'))
  client_id = db.Column(db.Integer, db.ForeignKey('client.id'))
  
  def __init__(self, text, timestamp = None):
    self.text = text

    if timestamp is None:
      self.timestamp = datetime.utcnow()

class User(db.Model):
  id = db.Column(db.Integer, primary_key = True)
  org_nickname = db.Column(db.String(64), unique = True)
  org_url = db.Column(db.String(64), unique = True)
  normalized_phone_number = db.Column(db.String(20), unique=True)
  raw_phone_number = db.Column(db.String(50))
  nickname = db.Column(db.String(64))
  email = db.Column(db.String(120))
  questions = db.relationship('Question', backref='user', lazy='dynamic')
  clients = db.relationship('Client',
              secondary=user_clients,
              backref=db.backref('users', lazy='dynamic'))

  def send_question(self, question):
    '''Send a question to all clients and add question to client.questions array'''
    clients = self.clients
    body = question.text
    self.questions.append(question)
    for c in clients:
      thr = Thread(target=send_message, args=(c.normalized_phone_number, body))
      thr.start()
      c.questions.append(question)
      db.session.add(c)
    db.session.commit()

  def remove_client(self, client):
    self.clients.remove(client)
    db.session.add(self)
    db.session.commit()
  
  def is_authenticated(self):
    return True

  def is_active(self):
    return True

  def is_anonymous(self):
    return False

  def get_id(self):
    return unicode(self.id)

  def __init__(self, raw_phone_number, org_nickname):
    self.raw_phone_number = raw_phone_number
    self.normalized_phone_number = normalize_phone_number(raw_phone_number)
    self.org_nickname = org_nickname
    self.org_url = org_nickname_to_url(org_nickname)

  def __repr__(self):
      return '<User phone:%r org:%r>' % (self.normalized_phone_number, self.org_nickname)

# Forms
class QuestionForm(Form):
    question_text = TextAreaField('Question',[validators.required(), validators.length(max=160, min=10)])

class ImportForm(Form):
    phone_numbers = TextAreaField('Clients',[validators.required()])

    def validate(self):
      rv = Form.validate(self)
      if not rv:
        return False
      return True

class LoginForm(Form):
    phone_number = TextField(validators=[validators.required()])

    def validate(self):
      rv = Form.validate(self)
      if not rv:
        return False
      u = self.get_user()
      if not u:
        return False
      else:
        return True

    def get_user(self):
      return User.query.filter_by(normalized_phone_number = normalize_phone_number(self.phone_number.data)).first()

class RegistrationForm(Form):
  phone_number = TextField(validators=[validators.required()])
  org_nickname = TextField(validators=[validators.required()])

  def validate(self):
    rv = Form.validate(self)
    if not rv:
      return False
    # check for duplicate phone
    normalized_phone_number = normalize_phone_number(self.phone_number.data)
    u = User.query.filter_by(normalized_phone_number = normalized_phone_number).first()
    if u:
      return False
    # check for duplicate org
    u = User.query.filter_by(org_nickname = self.org_nickname.data).first()
    if u:
      return False
    # check for duplicate url
    u = User.query.filter_by(org_url = org_nickname_to_url(self.org_nickname.data)).first()
    if u:
      return False
    # good to go!
    return True

# Utils
def parse_phone_numbers(text):
  #TODO some validation here?
  return text.splitlines()

def find_user_by_keyword_msg(msg):
  keyword = re.sub('#', '', msg.strip())
  user = User.query.filter_by(org_url = keyword).first()
  return user if user else None

def normalize_phone_number(phone_number):
  digits = re.compile(r'[^\d]+')
  phone_digits = digits.sub('', phone_number)
  return '1' + phone_digits if len(phone_digits) == 10 else phone_digits

def org_nickname_to_url(org_nickname):
    url = re.sub('[!@#$]', '', org_nickname)
    url = url.strip()
    url = url.replace(" ","-")
    url = url.lower()
    return url

def get_or_create_client(phone_number):
  '''Return an existing client or create a new one'''
  normalized_phone_number = normalize_phone_number(phone_number)
  c = Client.query.filter_by(normalized_phone_number = normalized_phone_number).first()
  status = 'old'
  if not c:
    c = Client(raw_phone_number = phone_number)
    status = 'new'
    db.session.add(c)
    db.session.commit()
  return c, status

def send_message(phone_number, body):
  '''Send SMS to a phone_number using our twilio account'''
  account_sid = os.environ['TWILIO_SID']
  auth_token = os.environ['TWILIO_AUTH']
  twilio_number = os.environ['TWILIO_NUM']
  client = TwilioRestClient(account_sid, auth_token)
  try:
    client.messages.create(to=phone_number, from_=twilio_number, body=body[:160])
  except Exception:
    app.logger.warning('Failed to send message to %s)' % phone_number)
  return body

# DB Utils
def reset_db():
  db.drop_all()
  db.create_all()
  seed_db()

def seed_db():
  u1 = User(raw_phone_number = '1', org_nickname = 'jake')
  c1 = Client(raw_phone_number = '2')
  c2 = Client(raw_phone_number = '3')
  q1 = Question('Test quesiton 1')
  q2 = Question('Test question 2')
  a1 = Answer('First answer to first question')
  a2 = Answer('Second answer to first question')
  a3 = Answer('Answer to 2nd question')
  more_answers = [Answer('Answer...') for a in range(10)]
  u1.questions.extend([q1, q2])
  u1.clients.extend([c1, c2])
  c1.questions.extend([q1, q2])
  c1.answers.extend([a1, a3] + more_answers)
  c2.answers.extend([a2])
  q1.answers.extend([a1, a2] + more_answers)
  q2.answers.append(a3)
  db.session.add_all([u1, c1, c2, q1, q2, a1, a2, a3] + more_answers)
  db.session.commit()