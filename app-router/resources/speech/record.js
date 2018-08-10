(function audioInit(){
    var context = new AudioContext();
    var globalSocket;

    var stopBtn = document.getElementById('stopBtn');
    var startBtn = document.getElementById('startBtn');

    var websocketPromise = new Promise((resolve, reject) => {
        var socket = io.connect('wss://core-py.hanapm.local.com:30033/transcribe');
        socket.on('open', resolve(socket));
        socket.on('error', reject());
    });

    websocketPromise.then((socket) => {
        globalSocket = socket;
        socket.on('message', (e) => {
            console.log('Received from server: ' + e);
        });
        socket.on('error', (e) => {
            console:log('Error from websocket: ' + e);
            closeWebsocket();
        });
        socket.on('speechResponse', (input) => {
            var audioResponse  = input.audio;
            var textResponse = input.text;
            console.log('Response: ' + textResponse);
            addToPanel('<strong>Response: </strong>' + textResponse);

            context.decodeAudioData(audioResponse, function(buffer) {
                var source = context.createBufferSource();
                var myBuffer = buffer;
                source.buffer = myBuffer;
                source.connect(context.destination);
                source.start(0);
            });
        });
        socket.on('textResponse', (input) => {
            console.log('Response: ' + input);
            addToPanel('<strong>Response: </strong>' + input);
        });
        socket.on('transcribeSuccess', (input) => {
            console.log('Command: ' + input);
            addToPanel('<strong>Command: </strong>' + input);
        });

        function closeWebsocket() {
            if (microphone) microphone.disconnect();
            if (socket && socket.readyState === socket.OPEN) socket.close();
        }

        function addToPanel(msg){
            var panel = document.getElementById('panel');
            var p = document.createElement('p');
            p.innerHTML = msg;
            panel.appendChild(p);
        }
    });

    startBtn.addEventListener('click', () => {
        var panelTitle = document.getElementById('panelTitle');
        panelTitle.innerHTML = '<h2>HANA Speech Assistant - Listening...</h2>'

        startBtn.disabled = true;
        stopBtn.disabled = false;

        navigator.mediaDevices.getUserMedia({
            audio: true,
            video: false
        }).then((micStream) => {
            var microphone = context.createMediaStreamSource(micStream);
            var rec = new Recorder(microphone, {
                numChannels: 1
            });
            rec.record();
            console.log('Started recording');

            stopBtn.addEventListener('click', stopRecording);
            function stopRecording(){
                console.log('Stopped recording.');
                panelTitle.innerHTML = '<h2>HANA Speech Assistant</h2>';

                stopBtn.disabled = true;
                startBtn.disabled = false;

                rec.stop();
                micStream.getAudioTracks()[0].stop();
                rec.exportWAV(shareAudio);
            }

            function shareAudio(blob){
                globalSocket.emit('streamForTranscription', blob);
                console.log('Sent for transcription.');
                stopBtn.removeEventListener('click', stopRecording);
            }
        });
    })
})();

