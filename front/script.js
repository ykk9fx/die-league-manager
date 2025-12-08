// script.js
const BASE_URL = 'http://127.0.0.1:5000/api/auth';
const statusMessage = document.getElementById('status-message');

// --- Utility Function to Display Messages ---
function displayMessage(message, isSuccess = true) {
    statusMessage.textContent = message;
    statusMessage.className = isSuccess ? 'message success' : 'message error';
    statusMessage.style.display = 'block';
}

// --- API Communication Function (Core Logic) ---
async function sendAuthRequest(endpoint, data) {
    try {
        const response = await fetch(`${BASE_URL}/${endpoint}`, {
            method: 'POST',
            mode: 'cors',                     // ★ required for CORS
            credentials: 'include',           // ★ required for cookies / Flask session
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (response.ok) {
            displayMessage(result.message, true);
        } else {
            displayMessage(`Error: ${result.error}`, false);
        }
    } catch (error) {
        displayMessage('Network error. Is the Flask server running?', false);
        console.error("Fetch Error:", error);
    }
}

// --- Form Submission Handlers ---

// Handle Registration
document.getElementById('register-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('reg-name').value;
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;

    await sendAuthRequest('register', { name, email, password });
});

// Handle Login
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;

    await sendAuthRequest('login', { email, password });
});

// --- Test Protected League Retrieval ---
document.addEventListener('DOMContentLoaded', () => {
    const testButton = document.createElement('button');
    testButton.textContent = "Test Protected League Data";
    document.body.appendChild(testButton);

    testButton.addEventListener('click', async () => {
        const response = await fetch('http://127.0.0.1:5000/api/league', {
            method: 'GET',
            mode: 'cors',              // must match login
            credentials: 'include'     // must send session cookie
        });

        const result = await response.json();

        if (response.ok) {
            console.log("Protected Data Received:", result);
            displayMessage(`Successfully fetched ${result.length} leagues!`, true);
        } else {
            displayMessage(`Failed to fetch: ${result.error}`, false);
        }
    });
});
