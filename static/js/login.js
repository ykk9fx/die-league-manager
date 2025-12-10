// C:\projects\league-manager-api\static\js\login.js

const API_ROOT = 'http://127.0.0.1:5000/api/auth/';
const loginView = document.getElementById('loginView');
const registerView = document.getElementById('registerView');
const messageDiv = document.getElementById('message');

// --- Utility Functions ---

function showMessage(type, text) {
    messageDiv.className = type; // 'success' or 'error'
    messageDiv.textContent = text;
    messageDiv.classList.remove('hidden');
}

function hideMessage() {
    messageDiv.classList.add('hidden');
    messageDiv.textContent = '';
}

function switchView(viewName) {
    hideMessage();
    if (viewName === 'register') {
        // Hide Login, Show Register
        loginView.classList.add('hidden');
        registerView.classList.remove('hidden');
    } else { // 'login'
        // Hide Register, Show Login
        registerView.classList.add('hidden'); // <-- Ensure Register is hidden on 'login'
        loginView.classList.remove('hidden');
    }
}

// --- Event Listeners for View Switching ---

document.getElementById('showRegister').addEventListener('click', (e) => {
    e.preventDefault();
    switchView('register');
});

document.getElementById('showLogin').addEventListener('click', (e) => {
    e.preventDefault();
    switchView('login');
});

// --- API Communication Function (Generic) ---

async function sendAuthRequest(endpoint, data) {
    // ... (rest of sendAuthRequest remains the same)
    const response = await fetch(API_ROOT + endpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(data)
    });

    const contentType = response.headers.get("content-type");
    let result;
    if (contentType && contentType.indexOf("application/json") !== -1) {
        result = await response.json();
    } else {
        const text = await response.text();
        result = { error: text || response.statusText };
    }
    
    return { status: response.status, data: result };
}


// --- LOGIN Submission ---

document.getElementById('loginForm').addEventListener('submit', async function(event) {
    event.preventDefault();
    hideMessage();

    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;
    
    const { status, data } = await sendAuthRequest('login', { email, password });

    if (status === 200) {
        showMessage('success', `Login successful! Welcome, ${data.name}. Redirecting...`);
        
        // --- NEW REDIRECT LOGIC ---
        if (data.redirect_url) {
            window.location.href = data.redirect_url;
        }
        // ------------------------

    } else {
        showMessage('error', data.error || 'Invalid credentials or server error.');
    }
});


// --- REGISTRATION Submission ---

document.getElementById('registerForm').addEventListener('submit', async function(event) {
    event.preventDefault();
    hideMessage();

    const name = document.getElementById('reg-name').value;
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;
    
    const { status, data } = await sendAuthRequest('register', { name, email, password });

    if (status === 201) {
        showMessage('success', data.message || 'Registration successful! Please log in.');
        
        // Auto-switch to login view after success
        setTimeout(() => switchView('login'), 2000); 

    } else {
        showMessage('error', data.error || 'Registration failed due to server error.');
    }
});

// Initialize view on load
// This ensures the correct views are shown/hidden right when the page finishes loading.
switchView('login');