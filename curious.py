import os, urllib2, json, re
from random import choice
from twilio.rest import TwilioRestClient
from datetime import datetime, timedelta, date
from babel.dates import format_datetime
from flask import Flask, request, render_template, redirect
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy import desc

# Setup app
app = Flask(__name__)
app.config['DEBUG'] = os.environ['DEBUG']
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ['DATABASE_URL']
db = SQLAlchemy(app)

# Routes
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

@app.route('/')
def index():
  slogans = [
    'Dead simple SMS feedback for nonprofits.',
    'Get anonymous feedback from your clients over text message.',
    'Ask anything. Get honest answers.'
    ]
  s = choice(slogans)
  return render_template('index.html', slogan = s)

@app.route('/sms')
def sms():
  # get client
  from_number = request.values.get('From')
  c = get_or_create_client(from_number)

  # get last q
  q = Question.get_most_recent_question()

  # create answer
  msg = request.values.get('Body')
  a = Answer(text = msg)

  # save + commit everything
  q.answers.append(a)
  c.answers.append(a)
  c.questions.append(q)
  db.session.add(c)
  db.session.add(q)
  db.session.add(a)
  db.session.commit()

# Models
client_questions = db.Table('client_questions',
    db.Column('client_id', db.Integer, db.ForeignKey('client.id')),
    db.Column('question_id', db.Integer, db.ForeignKey('question.id'))
)

class Client(db.Model):
  '''Clients receive questions and answer them'''
  id = db.Column(db.Integer, primary_key=True)
  phone_number = db.Column(db.String(20), unique=True)
  answers = db.relationship('Answer', backref='client', lazy='dynamic')
  questions = db.relationship('Question',
              secondary=client_questions,
              backref=db.backref('clients', lazy='dynamic'))

class Question(db.Model):
  '''Questions are sent to clients and have answers'''
  id = db.Column(db.Integer, primary_key=True)
  timestamp = db.Column(db.DateTime)
  text = db.Column(db.String)
  answers = db.relationship('Answer', backref='question', lazy='dynamic')
  
  def __init__(self, text, timestamp = None):
    self.text = text
    if timestamp is None:
      self.timestamp = datetime.utcnow()

  @classmethod
  def get_most_recent_question(cls):
    return cls.query.order_by(desc(cls.timestamp)).first()

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

# Utils
def get_or_create_client(phone_number):
  '''Return an existing client or create a new one'''
  c = Client.query.filter_by(phone_number = phone_number).first()
  if not c:
    c = Client(phone_number = phone_number)
    db.session.add(c)
    db.session.commit()
  return c

def send_question(question):
  '''Send a question to all clients and add question to client.questions array'''
  clients = Client.query.all()
  body = question.text
  for c in clients:
    send_message(c.phone_number, body)
    c.questions.append(question)
    db.session.add(c)
  db.session.commit()

def send_message(phone_number, body):
  '''Send SMS to a phone_number using our twilio account'''
  account_sid = os.environ['TWILIO_SID']
  auth_token = os.environ['TWILIO_AUTH']
  twilio_number = os.environ['TWILIO_NUM']
  client = TwilioRestClient(account_sid, auth_token)
  client.sms.messages.create(to=phone_number, from_=twilio_number, body=body[:160])
  return body