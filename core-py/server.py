import os
import json
import re
import logging
from flask import *
from cfenv import AppEnv
from hdbcli import dbapi
from cf_logging import flask_logging
from sap import xssec
from flask_socketio import SocketIO
from flask_socketio import send, emit, Namespace

#create instance of flask app
app = Flask(__name__)
socketio = SocketIO(app)
app_port = int(os.environ.get('PORT', 3000))

#connection with services
env = AppEnv()
hana = env.get_service(name='hdi-db')
uaa_service = env.get_service(name='myuaa').credentials

#logging
flask_logging.init(app, logging.INFO)
logger = logging.getLogger('route.logger')

''' HELPER FUNCTIONS '''

#used to establish connection with HANA DB
def connectDB(serviceName):
    service = env.get_service(name=serviceName)
    conn = dbapi.connect(address=service.credentials['host'],
                         port= int(service.credentials['port']),
                         user = service.credentials['user'],
                         password = service.credentials['password'],
                         CURRENTSCHEMA=service.credentials['schema'])
    return conn

#used to check if user is authorized
def checkAuth(header):
    if 'authorization' not in request.headers:
        return False
    
    access_token = header.get('authorization')[7:]
    security_context = xssec.create_security_context(access_token, uaa_service)
    isAuthorized = security_context.check_scope('openid') or security_context.check_scope('uaa.resource')

    logger.info("Access token: " + access_token)

    if not isAuthorized:
        return False

    return True

def viewProduct(category):
    #establish db connection
    conn = connectDB('hdi-db')
    logger.info('Database connection successful: ' + str(conn.isconnected()))

    cursor = conn.cursor()

    query = 'SELECT * FROM "Product.Products" WHERE CATEGORY=?'
    
    logger.info(category)
    cursor.execute(query, category)

    #format results in to a list of JSON objects
    results = []
    i = 0
    for row in cursor.fetchall():
        i = i + 1
        results.append(json.dumps({str(i): str(row)}))

    #send response
    return results

def addProduct(ID, category, price):

    #establish db connection
    conn = connectDB('hdi-db')
    logger.info('Database connection successful: ' + str(conn.isconnected()))

    cursor = conn.cursor()

    in_params = (ID, category, price, None)
    output = cursor.callproc('"insert_product_data"', in_params)
    
    cursor.close()

    return str(output[3])

def audioSynthesis(text):
    from google.cloud import texttospeech as tts

    client = tts.TextToSpeechClient()

    input_text = tts.types.SynthesisInput(text=text)

    voice = tts.types.VoiceSelectionParams(
            language_code = 'en-US',
            ssml_gender = tts.enums.SsmlVoiceGender.FEMALE)

    audio_config = tts.types.AudioConfig(audio_encoding = tts.enums.AudioEncoding.LINEAR16)

    response = client.synthesize_speech(input_text, voice, audio_config)
    return response.audio_content

def transcribe(blob):
    from google.cloud import speech
    from google.cloud.speech import enums
    from google.cloud.speech import types

    client = speech.SpeechClient()
    
    audio = types.RecognitionAudio(content = blob)
    config = types.RecognitionConfig(
        language_code = 'en-US'
    )

    response = client.recognize(config, audio)
    logger.info(str(response))

    if response.results[0] is None:
        return "Error in speech transcription"
    else:
        return response.results[0].alternatives[0].transcript

def getCategory(command):
    #establish db connection
    conn = connectDB('hdi-db')
    logger.info('Database connection successful: ' + str(conn.isconnected()))

    cursor = conn.cursor()

    query = 'SELECT DISTINCT CATEGORY FROM "Product.Products"'
    cursor.execute(query)

    categories = []
    for col in cursor.fetchall():
        categories.append(col[0])

    words = [word.capitalize() for word in command.split()]
    category = str(set(categories).intersection(words))[2:-2]
    logger.info('Categories: %s \n Words: %s' % (str(categories), str(words)))

    return category
    
def executeCommand(command):
    read = True

    if ('add product' in command.lower()):
        ID = re.search('([0-9]){3}', command)[0].replace(' ', '')
        price = re.search('[0-9]*\.[0-9]*', command)[0]
        category = getCategory(command)

        logger.info('ID: %s, Category: %s, price: %s' % (str(ID), str(category), str(price)))
        response = addProduct(ID, category, price)
    elif ('show' in command.lower()):
        category = getCategory(command)
        response = viewProduct(category)
        read = False
    else:
        response = 'Invalid command'
    
    return (response, read)

''' ROUTES '''

@app.route('/')
def hello():
    #authorize user
    logger.info('Authorization successful') if checkAuth(request.headers) else abort(403)
    
    return "Welcome to SAP HANA Speech Demo!"

''' WEBSCOKET IMPLEMENTATION '''
class SpeechWsNamespace(Namespace):
    def on_connect(self):
        logger.info('Connected to client!')
        send('Connected to server!')
    
    def on_message(self, msg):
        logger.info('Received from client: %s' % msg)
    
    def on_streamForTranscription(self, blob):
        command = transcribe(blob)
        emit('transcribeSuccess', command, broadcast=True)

        response, read = executeCommand(command)
        logger.info('Command: %s. Response: %s. Read: %s.' % (command, response, read))

        if (read):
            resAudio = audioSynthesis(response)
            emit('speechResponse', {"audio": resAudio, "text": response}, broadcast=True)
        else:
            emit('textResponse', response, broadcast=True)
        
        logger.info('response sent after transcription')
    
    def on_error(self, e):
        logger.info('Error in websocket connection: %s' % e)

socketio.on_namespace(SpeechWsNamespace('/transcribe'))

''' START APP '''

if __name__ == '__main__':
    socketio.run(app, port=app_port)