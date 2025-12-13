/**
 * OpenAI Realtime Voice Card
 * 
 * A Lovelace card that captures microphone audio and streams it
 * to the OpenAI Realtime API via Home Assistant WebSocket.
 */

class OpenAIRealtimeCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._hass = null;
    this._config = {};
    this._isListening = false;
    this._isProcessing = false;
    this._isSpeaking = false;
    this._isConnected = false;
    this._mediaRecorder = null;
    this._audioContext = null;
    this._playbackContext = null;
    this._audioWorklet = null;
    this._stream = null;
    this._subscriptionId = null;
    this._unsubscribe = null;
    this._audioQueue = [];
    this._isPlayingAudio = false;
    this._currentAudioSource = null;
    this._transcript = '';
    this._responseText = '';
    this._audioSent = false;
  }

  set hass(hass) {
    this._hass = hass;
    this._updateState();
  }

  setConfig(config) {
    this._config = {
      title: config.title || 'OpenAI Realtime',
      show_transcript: config.show_transcript !== false,
      show_response: config.show_response !== false,
      sample_rate: config.sample_rate || 24000,
      ...config,
    };
    this._render();
  }

  static getConfigElement() {
    return document.createElement('openai-realtime-card-editor');
  }

  static getStubConfig() {
    return {
      title: 'OpenAI Realtime',
      show_transcript: true,
      show_response: true,
    };
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
        }
        ha-card {
          padding: 16px;
        }
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 16px;
        }
        .title {
          font-size: 1.2em;
          font-weight: 500;
        }
        .status {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .status-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          background-color: var(--disabled-color);
        }
        .status-dot.connected {
          background-color: var(--success-color, #4caf50);
        }
        .status-dot.listening {
          background-color: var(--warning-color, #ff9800);
          animation: pulse 1s infinite;
        }
        .status-dot.speaking {
          background-color: var(--info-color, #2196f3);
          animation: pulse 0.5s infinite;
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        .controls {
          display: flex;
          justify-content: center;
          margin: 16px 0;
        }
        .mic-button {
          width: 80px;
          height: 80px;
          border-radius: 50%;
          border: none;
          background-color: var(--primary-color);
          color: white;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.3s ease;
          box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }
        .mic-button:hover {
          transform: scale(1.05);
        }
        .mic-button:active {
          transform: scale(0.95);
        }
        .mic-button.listening {
          background-color: var(--error-color, #f44336);
          animation: pulse-button 1s infinite;
        }
        .mic-button.processing {
          background-color: var(--warning-color, #ff9800);
        }
        @keyframes pulse-button {
          0%, 100% { box-shadow: 0 0 0 0 rgba(244, 67, 54, 0.4); }
          50% { box-shadow: 0 0 0 20px rgba(244, 67, 54, 0); }
        }
        .mic-icon {
          width: 32px;
          height: 32px;
        }
        .transcript-container {
          margin-top: 16px;
          padding: 12px;
          background-color: var(--secondary-background-color);
          border-radius: 8px;
          min-height: 40px;
        }
        .transcript-label {
          font-size: 0.8em;
          color: var(--secondary-text-color);
          margin-bottom: 4px;
        }
        .transcript-text {
          font-size: 1em;
          line-height: 1.4;
        }
        .response-container {
          margin-top: 12px;
          padding: 12px;
          background-color: var(--primary-background-color);
          border: 1px solid var(--divider-color);
          border-radius: 8px;
          min-height: 40px;
        }
        .visualizer {
          display: flex;
          align-items: center;
          justify-content: center;
          height: 40px;
          gap: 3px;
          margin: 8px 0;
        }
        .visualizer-bar {
          width: 4px;
          background-color: var(--primary-color);
          border-radius: 2px;
          transition: height 0.1s ease;
        }
        .error-message {
          color: var(--error-color);
          font-size: 0.9em;
          margin-top: 8px;
          text-align: center;
        }
      </style>
      <ha-card>
        <div class="header">
          <div class="title">${this._config.title}</div>
          <div class="status">
            <div class="status-dot" id="status-dot"></div>
            <span id="status-text">Disconnected</span>
          </div>
        </div>
        
        <div class="visualizer" id="visualizer" style="display: none;">
          ${Array(20).fill(0).map(() => '<div class="visualizer-bar" style="height: 5px;"></div>').join('')}
        </div>
        
        <div class="controls">
          <button class="mic-button" id="mic-button">
            <svg class="mic-icon" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.91-3c-.49 0-.9.36-.98.85C16.52 14.2 14.47 16 12 16s-4.52-1.8-4.93-4.15c-.08-.49-.49-.85-.98-.85-.61 0-1.09.54-1 1.14.49 3 2.89 5.35 5.91 5.78V20c0 .55.45 1 1 1s1-.45 1-1v-2.08c3.02-.43 5.42-2.78 5.91-5.78.1-.6-.39-1.14-1-1.14z"/>
            </svg>
          </button>
        </div>
        
        ${this._config.show_transcript ? `
          <div class="transcript-container">
            <div class="transcript-label">You said:</div>
            <div class="transcript-text" id="transcript-text">...</div>
          </div>
        ` : ''}
        
        ${this._config.show_response ? `
          <div class="response-container">
            <div class="transcript-label">Response:</div>
            <div class="transcript-text" id="response-text">...</div>
          </div>
        ` : ''}
        
        <div class="error-message" id="error-message" style="display: none;"></div>
      </ha-card>
    `;

    this._setupEventListeners();
  }

  _setupEventListeners() {
    const micButton = this.shadowRoot.getElementById('mic-button');
    if (micButton) {
      micButton.addEventListener('click', () => this._toggleListening());
    }
  }

  async _toggleListening() {
    if (this._isListening) {
      await this._stopListening();
    } else {
      await this._startListening();
    }
  }

  async _startListening() {
    try {
      this._clearError();
      
      // Connect to OpenAI Realtime via WebSocket
      await this._connect();
      
      // Subscribe to events
      await this._subscribe();
      
      // Get microphone access - don't specify sample rate, use browser's native rate
      this._stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        }
      });

      // Set up audio processing
      await this._setupAudioProcessing();
      
      this._isListening = true;
      this._audioSent = false;
      this._transcript = '';
      this._responseText = '';
      this._updateUI();
      
    } catch (error) {
      console.error('Error starting listening:', error);
      this._showError(error.message);
      await this._stopListening();
    }
  }

  async _stopListening() {
    this._isListening = false;
    
    // Stop any ongoing audio playback first
    this._stopAudioPlayback();
    
    // Stop audio processing
    if (this._audioWorklet) {
      this._audioWorklet.disconnect();
      this._audioWorklet = null;
    }
    
    if (this._audioContext) {
      await this._audioContext.close();
      this._audioContext = null;
    }
    
    // Stop media stream
    if (this._stream) {
      this._stream.getTracks().forEach(track => track.stop());
      this._stream = null;
    }
    
    // Commit audio buffer only if we actually sent audio
    if (this._hass && this._audioSent && this._isConnected) {
      try {
        await this._hass.callWS({
          type: 'openai_realtime/commit_audio',
        });
      } catch (e) {
        // Ignore errors on commit
        console.log('Commit audio failed (may be empty):', e);
      }
    }
    
    // Unsubscribe from events when stopping
    if (this._unsubscribe) {
      try {
        this._unsubscribe();
      } catch (e) {
        console.log('Unsubscribe error:', e);
      }
      this._unsubscribe = null;
    }
    
    // Disconnect from OpenAI Realtime API
    if (this._hass && this._isConnected) {
      try {
        console.log('Disconnecting from OpenAI Realtime API...');
        await this._hass.callWS({
          type: 'openai_realtime/disconnect',
        });
        console.log('Disconnected from OpenAI Realtime API');
      } catch (e) {
        console.log('Disconnect error:', e);
      }
      this._isConnected = false;
    }
    
    this._updateUI();
  }

  async _setupAudioProcessing() {
    // Create AudioContext WITHOUT specifying sample rate - it will use system default
    // This ensures it matches the MediaStream's sample rate
    this._audioContext = new (window.AudioContext || window.webkitAudioContext)();
    
    // Wait for context to be ready
    if (this._audioContext.state === 'suspended') {
      await this._audioContext.resume();
    }
    
    const nativeSampleRate = this._audioContext.sampleRate;
    const targetSampleRate = this._config.sample_rate; // 24000
    
    console.log(`Audio: native=${nativeSampleRate}Hz, target=${targetSampleRate}Hz`);

    const source = this._audioContext.createMediaStreamSource(this._stream);
    
    // Use ScriptProcessor for wider compatibility
    const bufferSize = 4096;
    const processor = this._audioContext.createScriptProcessor(bufferSize, 1, 1);
    
    processor.onaudioprocess = (e) => {
      if (!this._isListening) return;
      
      const inputData = e.inputBuffer.getChannelData(0);
      
      // Resample from native rate to target rate (24kHz)
      const resampledData = this._resample(inputData, nativeSampleRate, targetSampleRate);
      
      // Convert Float32 to Int16 PCM
      const pcmData = this._float32ToInt16(resampledData);
      
      // Convert to base64 and send
      const base64Audio = this._arrayBufferToBase64(pcmData.buffer);
      this._sendAudio(base64Audio);
      
      // Update visualizer
      this._updateVisualizer(inputData);
    };
    
    source.connect(processor);
    processor.connect(this._audioContext.destination);
    
    this._audioWorklet = processor;
  }

  _resample(inputData, fromRate, toRate) {
    if (fromRate === toRate) {
      return inputData;
    }
    
    const ratio = fromRate / toRate;
    const outputLength = Math.round(inputData.length / ratio);
    const output = new Float32Array(outputLength);
    
    for (let i = 0; i < outputLength; i++) {
      const srcIndex = i * ratio;
      const srcIndexFloor = Math.floor(srcIndex);
      const srcIndexCeil = Math.min(srcIndexFloor + 1, inputData.length - 1);
      const t = srcIndex - srcIndexFloor;
      
      // Linear interpolation
      output[i] = inputData[srcIndexFloor] * (1 - t) + inputData[srcIndexCeil] * t;
    }
    
    return output;
  }

  _float32ToInt16(float32Array) {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array;
  }

  _arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  _base64ToArrayBuffer(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
  }

  async _sendAudio(base64Audio) {
    if (!this._hass || !this._isConnected) return;
    
    try {
      await this._hass.callWS({
        type: 'openai_realtime/send_audio',
        audio: base64Audio,
      });
      this._audioSent = true;
    } catch (error) {
      console.error('Error sending audio:', error);
    }
  }

  async _connect() {
    if (!this._hass) {
      throw new Error('Home Assistant not available');
    }
    
    console.log('Connecting to OpenAI Realtime...');
    const result = await this._hass.callWS({
      type: 'openai_realtime/connect',
    });
    console.log('Connection result:', result);
    
    if (!result.connected) {
      throw new Error('Failed to connect to OpenAI Realtime API');
    }
    
    // Wait a bit for the session to be established
    await new Promise(resolve => setTimeout(resolve, 500));
    
    this._isConnected = true;
  }

  async _subscribe() {
    if (!this._hass) return;
    
    // Unsubscribe first if already subscribed to prevent duplicate handlers
    if (this._unsubscribe) {
      console.log('Already subscribed, unsubscribing first...');
      try {
        this._unsubscribe();
      } catch (e) {
        console.log('Unsubscribe error:', e);
      }
      this._unsubscribe = null;
    }
    
    console.log('Subscribing to OpenAI Realtime events...');
    
    // Subscribe to events
    try {
      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (msg) => {
          console.log('Received event:', msg);
          this._handleEvent(msg);
        },
        { type: 'openai_realtime/subscribe' }
      );
      console.log('Subscribed successfully');
    } catch (error) {
      console.error('Subscribe error:', error);
    }
  }

  _handleEvent(msg) {
    // Handle both direct event format and nested event format
    const event = msg.event || msg;
    
    if (!event || !event.type) {
      console.log('No event type in message:', msg);
      return;
    }
    
    console.log('Processing event:', event.type, event);
    
    switch (event.type) {
      case 'speech_started':
        this._isProcessing = false;
        // Stop any ongoing audio playback when user starts speaking
        this._stopAudioPlayback();
        // Clear the response text for new response
        this._responseText = '';
        this._updateResponse();
        this._updateUI();
        break;
        
      case 'speech_stopped':
        this._isProcessing = true;
        this._updateUI();
        break;
        
      case 'user_transcript':
        // User's speech transcription (what the user said)
        this._transcript = event.transcript || '';
        this._updateTranscript();
        break;
        
      case 'response_transcript_delta':
        // AI's response transcript (streaming)
        this._responseText += event.delta || '';
        this._updateResponse();
        break;
        
      case 'response_transcript_done':
        // AI's response transcript complete
        if (event.transcript) {
          this._responseText = event.transcript;
          this._updateResponse();
        }
        break;
        
      case 'text_delta':
        // Text response (non-audio)
        this._responseText += event.delta || '';
        this._updateResponse();
        break;
        
      case 'audio_delta':
        if (event.audio) {
          console.log('Received audio chunk, length:', event.audio.length);
          this._queueAudio(event.audio);
        }
        break;
        
      case 'response_done':
        this._isProcessing = false;
        this._updateUI();
        break;
    }
  }

  _stopAudioPlayback() {
    // Clear the audio queue
    this._audioQueue = [];
    this._isPlayingAudio = false;
    this._isSpeaking = false;
    
    // Stop current audio source if playing
    if (this._currentAudioSource) {
      try {
        this._currentAudioSource.stop();
      } catch (e) {
        // Ignore errors if already stopped
      }
      this._currentAudioSource = null;
    }
    
    console.log('Audio playback stopped');
  }

  _queueAudio(base64Audio) {
    // Only queue audio if we're still listening/active
    if (!this._isConnected) {
      console.log('Not connected, skipping audio queue');
      return;
    }
    
    this._audioQueue.push(base64Audio);
    
    if (!this._isPlayingAudio) {
      this._startAudioPlayback();
    }
  }

  async _startAudioPlayback() {
    if (this._audioQueue.length === 0) {
      this._isPlayingAudio = false;
      this._isSpeaking = false;
      this._updateUI();
      return;
    }
    
    this._isPlayingAudio = true;
    this._isSpeaking = true;
    this._updateUI();
    
    // Create a single playback context for all audio
    if (!this._playbackContext || this._playbackContext.state === 'closed') {
      this._playbackContext = new (window.AudioContext || window.webkitAudioContext)();
    }
    
    // Process all queued audio
    await this._playNextChunk();
  }

  async _playNextChunk() {
    if (this._audioQueue.length === 0) {
      this._isPlayingAudio = false;
      this._isSpeaking = false;
      this._currentAudioSource = null;
      this._updateUI();
      return;
    }
    
    const base64Audio = this._audioQueue.shift();
    
    try {
      const arrayBuffer = this._base64ToArrayBuffer(base64Audio);
      
      // Convert Int16 PCM to Float32
      const int16Data = new Int16Array(arrayBuffer);
      const float32Data = new Float32Array(int16Data.length);
      for (let i = 0; i < int16Data.length; i++) {
        float32Data[i] = int16Data[i] / 32768.0;
      }
      
      // Create audio buffer at 24kHz
      const sampleRate = this._config.sample_rate; // 24000
      const audioBuffer = this._playbackContext.createBuffer(1, float32Data.length, sampleRate);
      audioBuffer.copyToChannel(float32Data, 0);
      
      // Play audio
      const source = this._playbackContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this._playbackContext.destination);
      
      // Store reference so we can stop it
      this._currentAudioSource = source;
      
      source.onended = () => {
        this._currentAudioSource = null;
        this._playNextChunk();
      };
      
      source.start();
      console.log('Playing audio chunk, samples:', float32Data.length);
      
    } catch (error) {
      console.error('Error playing audio:', error);
      this._currentAudioSource = null;
      this._playNextChunk();
    }
  }

  async _playAudio(base64Audio) {
    // Legacy method - redirect to new queue system
    this._queueAudio(base64Audio);
  }

  _updateVisualizer(audioData) {
    const visualizer = this.shadowRoot.getElementById('visualizer');
    if (!visualizer) return;
    
    visualizer.style.display = this._isListening ? 'flex' : 'none';
    
    const bars = visualizer.querySelectorAll('.visualizer-bar');
    const step = Math.floor(audioData.length / bars.length);
    
    bars.forEach((bar, i) => {
      const start = i * step;
      let sum = 0;
      for (let j = 0; j < step; j++) {
        sum += Math.abs(audioData[start + j] || 0);
      }
      const average = sum / step;
      const height = Math.max(5, Math.min(40, average * 200));
      bar.style.height = `${height}px`;
    });
  }

  _updateUI() {
    const micButton = this.shadowRoot.getElementById('mic-button');
    const statusDot = this.shadowRoot.getElementById('status-dot');
    const statusText = this.shadowRoot.getElementById('status-text');
    const visualizer = this.shadowRoot.getElementById('visualizer');
    
    if (micButton) {
      micButton.classList.toggle('listening', this._isListening);
      micButton.classList.toggle('processing', this._isProcessing);
    }
    
    if (statusDot) {
      statusDot.classList.remove('connected', 'listening', 'speaking');
      if (this._isSpeaking) {
        statusDot.classList.add('speaking');
      } else if (this._isListening) {
        statusDot.classList.add('listening');
      } else if (this._hass) {
        statusDot.classList.add('connected');
      }
    }
    
    if (statusText) {
      if (this._isSpeaking) {
        statusText.textContent = 'Speaking...';
      } else if (this._isProcessing) {
        statusText.textContent = 'Processing...';
      } else if (this._isListening) {
        statusText.textContent = 'Listening...';
      } else {
        statusText.textContent = 'Ready';
      }
    }
    
    if (visualizer) {
      visualizer.style.display = this._isListening ? 'flex' : 'none';
    }
  }

  _updateTranscript() {
    const element = this.shadowRoot.getElementById('transcript-text');
    if (element) {
      element.textContent = this._transcript || '...';
    }
  }

  _updateResponse() {
    const element = this.shadowRoot.getElementById('response-text');
    if (element) {
      element.textContent = this._responseText || '...';
    }
  }

  _updateState() {
    // Update based on HA state
    this._updateUI();
  }

  _showError(message) {
    const element = this.shadowRoot.getElementById('error-message');
    if (element) {
      element.textContent = message;
      element.style.display = 'block';
    }
  }

  _clearError() {
    const element = this.shadowRoot.getElementById('error-message');
    if (element) {
      element.style.display = 'none';
    }
  }

  disconnectedCallback() {
    this._stopListening();
    if (this._unsubscribe) {
      this._unsubscribe();
    }
    if (this._playbackContext && this._playbackContext.state !== 'closed') {
      this._playbackContext.close();
    }
  }

  getCardSize() {
    return 4;
  }
}

// Only define if not already defined
if (!customElements.get('openai-realtime-card')) {
  customElements.define('openai-realtime-card', OpenAIRealtimeCard);
}

// Register the card (only once)
window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === 'openai-realtime-card')) {
  window.customCards.push({
    type: 'openai-realtime-card',
    name: 'OpenAI Realtime Card',
    description: 'A card for voice interaction with OpenAI Realtime API',
    preview: true,
  });
}

console.info('%c OPENAI-REALTIME-CARD %c Loaded', 
  'background: #4caf50; color: white; padding: 2px 6px; border-radius: 4px 0 0 4px;',
  'background: #1976d2; color: white; padding: 2px 6px; border-radius: 0 4px 4px 0;'
);
