// script.js (Update the existing file)

const BASE_URL = 'http://127.0.0.1:5000/api';
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
        const response = await fetch(`${BASE_URL}/auth/${endpoint}`, {
            method: 'POST',
            mode: 'cors',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (response.ok) {
            displayMessage(result.message, true);
            if (endpoint === 'login') {
                // *** NEW: Redirect to the leagues dashboard page ***
                window.location.href = 'leagues.html';
            }
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

// --- REMOVE: The protected data test is no longer relevant here ---
// It was removed because the new leagues.html now handles all data fetching.