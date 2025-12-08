const BASE_URL = 'http://127.0.0.1:5000/api';

function getLeagueIdFromUrl() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('league_id');
}

// Global variables
let currentLeagueId = null; 
let currentUserTeamId = null; 
let currentTeamsData = []; // To store team data for the Join Team dropdown

// --- MODAL ELEMENTS (Access dynamically, but declare constants for clarity) ---
const createTeamModal = document.getElementById('create-team-modal');
const createTeamForm = document.getElementById('create-team-form');
const createTeamMessage = document.getElementById('create-team-message');
const closeCreateTeamModalBtn = document.getElementById('close-create-team-modal-btn');

const joinTeamModal = document.getElementById('join-team-modal');
const joinTeamForm = document.getElementById('join-team-form');
const joinTeamMessage = document.getElementById('join-team-message');
const selectTeamDropdown = document.getElementById('select-team');
const closeJoinTeamModalBtn = document.getElementById('close-join-team-modal-btn');
// --------------------------------------------------------------------------

// Simple tab switcher (Globally accessible via window.showTab)
window.showTab = function(tabId) {
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.style.display = 'none';
    });
    document.getElementById(tabId).style.display = 'block';
}

document.addEventListener('DOMContentLoaded', () => {
    currentLeagueId = getLeagueIdFromUrl();
    
    if (!currentLeagueId) {
        document.getElementById('main-content').innerHTML = "<p class='error'>Error: League ID not found in URL.</p>";
        return;
    }

    // Initialize the view
    fetchLeagueDetails(currentLeagueId);
    
    // Back button logic
    document.getElementById('back-to-leagues-btn').addEventListener('click', () => {
        window.location.href = 'leagues.html';
    });

    // --- Modal Listeners (Static elements) ---
    // Create Team Listeners
    if (createTeamForm) {
        createTeamForm.addEventListener('submit', handleCreateTeam);
    }
    if (closeCreateTeamModalBtn) {
        closeCreateTeamModalBtn.addEventListener('click', () => {
            if (createTeamModal) createTeamModal.style.display = 'none';
        });
    }
    if (createTeamModal) {
        createTeamModal.addEventListener('click', (e) => {
            if (e.target === createTeamModal) {
                createTeamModal.style.display = 'none';
            }
        });
    }
    
    // Join Team Listeners
    if (joinTeamForm) {
        joinTeamForm.addEventListener('submit', handleJoinTeam);
    }
    if (closeJoinTeamModalBtn) {
        closeJoinTeamModalBtn.addEventListener('click', () => {
            if (joinTeamModal) joinTeamModal.style.display = 'none';
        });
    }
    if (joinTeamModal) {
        joinTeamModal.addEventListener('click', (e) => {
            if (e.target === joinTeamModal) {
                joinTeamModal.style.display = 'none';
            }
        });
    }
});


// --------------------------------------------------
// Fetch and Render Functions
// --------------------------------------------------

async function fetchLeagueDetails(leagueId) {
    try {
        const response = await fetch(`${BASE_URL}/league/${leagueId}/details`, {
            method: 'GET',
            mode: 'cors',
            credentials: 'include'
        });

        const data = await response.json();

        if (response.ok) {
            // Update league info section
            document.getElementById('league-name').textContent = data.league_name;
            document.getElementById('league-season').textContent = data.season_year;
            document.getElementById('league-status').textContent = data.status;
            document.getElementById('user-role').textContent = data.user_role;
            currentUserTeamId = data.user_team_id; // Will be null if user has no team
            
            // IMPORTANT: Save team data globally for use in the Join Team dropdown
            currentTeamsData = data.teams; 

            renderTeamManagement(data.user_team_id);
            renderTeamsList(data.teams);
        } else if (response.status === 401) {
            alert('Session expired. Redirecting to login.');
            window.location.href = 'index.html';
        } else {
            document.getElementById('main-content').innerHTML = `<p class='error'>Failed to load league: ${data.error}</p>`;
        }
    } catch (error) {
        console.error("Fetch League Details Error:", error);
        document.getElementById('main-content').innerHTML = "<p class='error'>Network error while fetching league data.</p>";
    }
}

/**
 * Handles rendering the team creation/management buttons.
 * This is where we attach listeners to dynamically created elements.
 */
function renderTeamManagement(userTeamId) {
    const managementDiv = document.getElementById('team-management');
    managementDiv.innerHTML = '';

    // Get modal elements dynamically inside this function too
    const createModal = document.getElementById('create-team-modal');
    const createForm = document.getElementById('create-team-form');
    const createMessage = document.getElementById('create-team-message');
    const joinModal = document.getElementById('join-team-modal');

    if (userTeamId) {
        // User has a team
        managementDiv.innerHTML = `<p class='success'>You are a member of Team ID: <strong>${userTeamId}</strong>.</p>
                                   <button id="edit-team-btn">Manage Team</button>`;
    } else {
        // User does not have a team
        managementDiv.innerHTML = `
            <p>You are currently not on a team in this league.</p>
            <button id="create-team-btn" class="btn-primary">Create New Team</button>
            <p>OR</p>
            <button id="join-team-btn" class="btn-secondary">Join Existing Team</button>
        `;
        
        // Attach listener for Create Team
        const createTeamBtn = document.getElementById('create-team-btn');
        if (createTeamBtn && createModal) {
            createTeamBtn.addEventListener('click', () => {
                createModal.style.display = 'block';
                if (createMessage) createMessage.style.display = 'none';
                if (createForm) createForm.reset();
            });
        }
        
        // Attach listener for Join Team
        const joinTeamBtn = document.getElementById('join-team-btn');
        if (joinTeamBtn && joinModal) {
            joinTeamBtn.addEventListener('click', () => {
                populateJoinTeamDropdown(); // Load available teams
                joinModal.style.display = 'block';
                if (joinTeamMessage) joinTeamMessage.style.display = 'none';
                if (joinTeamForm) joinTeamForm.reset();
            });
        }
    }
}

/**
 * Renders the list of teams, showing the player count.
 */
function renderTeamsList(teams) {
    const teamsListDiv = document.getElementById('teams-list');
    teamsListDiv.innerHTML = '';

    if (!teams || teams.length === 0) {
        teamsListDiv.innerHTML = '<p>No teams have been created in this league yet.</p>';
        return;
    }

    teams.forEach(team => {
        const teamItem = document.createElement('div');
        teamItem.className = 'team-item';
        teamItem.innerHTML = `
            <div>
                <strong>${team.team_name}</strong> (Players: ${team.member_count || 0})
            </div>
            <div>
                <button data-team-id="${team.team_id}" class="btn-secondary-sm">View Stats</button>
            </div>
        `;
        teamsListDiv.appendChild(teamItem);
    });
}


// --------------------------------------------------
// API Interaction Functions
// --------------------------------------------------

async function handleCreateTeam(event) {
    event.preventDefault();

    const teamName = document.getElementById('new-team-name').value;
    const modal = document.getElementById('create-team-modal');
    const message = document.getElementById('create-team-message');
    
    if (message) {
        message.textContent = 'Creating team...';
        message.className = 'message';
        message.style.display = 'block';
    }

    try {
        const response = await fetch(`${BASE_URL}/team`, {
            method: 'POST',
            mode: 'cors',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                league_id: currentLeagueId, 
                team_name: teamName 
            })
        });

        const result = await response.json();

        if (response.ok) {
            if (message) {
                message.textContent = result.message;
                message.className = 'message success';
            }

            setTimeout(() => {
                if (modal) modal.style.display = 'none';
                fetchLeagueDetails(currentLeagueId); // Refresh the main view
            }, 1500);

        } else {
            if (message) {
                message.textContent = `Error: ${result.error || 'Failed to create team.'}`;
                message.className = 'message error';
            }
        }
    } catch (error) {
        if (message) {
            message.textContent = 'Network error. Could not connect to server.';
            message.className = 'message error';
        }
        console.error("Create Team Error:", error);
    }
}

function populateJoinTeamDropdown() {
    // Only show teams that are not full (member_count < 2)
    const availableTeams = currentTeamsData.filter(team => team.member_count < 2);

    // Clear previous options
    if (selectTeamDropdown) selectTeamDropdown.innerHTML = '<option value="">-- Select a Team --</option>';

    if (availableTeams.length === 0) {
        if (selectTeamDropdown) selectTeamDropdown.innerHTML += '<option value="" disabled>No teams available to join.</option>';
    } else {
        availableTeams.forEach(team => {
            const option = document.createElement('option');
            option.value = team.team_id;
            option.textContent = `${team.team_name} (1 Player)`;
            if (selectTeamDropdown) selectTeamDropdown.appendChild(option);
        });
    }
}

async function handleJoinTeam(event) {
    event.preventDefault();

    const teamId = document.getElementById('select-team').value;
    const message = document.getElementById('join-team-message');
    const modal = document.getElementById('join-team-modal');

    if (!teamId) {
        if (message) {
            message.textContent = 'Please select a team.';
            message.className = 'message error';
            message.style.display = 'block';
        }
        return;
    }

    if (message) {
        message.textContent = 'Joining team...';
        message.className = 'message';
        message.style.display = 'block';
    }

    try {
        const response = await fetch(`${BASE_URL}/team/join`, {
            method: 'POST',
            mode: 'cors',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                league_id: currentLeagueId, 
                team_id: teamId 
            })
        });

        const result = await response.json();

        if (response.ok) {
            if (message) {
                message.textContent = result.message;
                message.className = 'message success';
            }

            // Success: Close modal and refresh league details
            setTimeout(() => {
                if (modal) modal.style.display = 'none';
                fetchLeagueDetails(currentLeagueId); // Refresh the main view
            }, 1500);

        } else {
            if (message) {
                message.textContent = `Error: ${result.error || 'Failed to join team.'}`;
                message.className = 'message error';
            }
        }
    } catch (error) {
        if (message) {
            message.textContent = 'Network error. Could not connect to server.';
            message.className = 'message error';
        }
        console.error("Join Team Error:", error);
    }
}