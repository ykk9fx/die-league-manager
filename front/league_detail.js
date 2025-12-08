// league_detail.js

const BASE_URL = 'http://127.0.0.1:5000/api';

function getLeagueIdFromUrl() {
    const urlParams = new URLSearchParams(window.location.search);
    return urlParams.get('league_id');
}

// Global variable for the current league/user context
let currentLeagueId = null; 
let currentUserTeamId = null; 

// Simple tab switcher
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


    
});

// league_detail.js (Continued)

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

// league_detail.js (Continued)

function renderTeamManagement(userTeamId) {
    const managementDiv = document.getElementById('team-management');
    managementDiv.innerHTML = '';
    
    if (userTeamId) {
        // User has a team
        managementDiv.innerHTML = `<p class='success'>You are the owner of Team ID: <strong>${userTeamId}</strong>.</p>
                                   <button id="edit-team-btn">Manage Team</button>`;
        // Note: Logic for 'Manage Team' will link to team_detail.html
    } else {
        // User does not have a team
        managementDiv.innerHTML = `
            <p>You are currently not managing a team in this league.</p>
            <button id="create-team-btn">Create New Team</button>
            <p>OR</p>
            <button id="join-team-btn" disabled>Join Existing Team (Future feature)</button>
        `;
        // Attach listener for Create Team (we'll implement the modal/logic next)
        document.getElementById('create-team-btn').addEventListener('click', () => {
            // Placeholder: Show Create Team Modal
            alert("Open Create Team Modal"); 
        });
    }
}

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
                <strong>${team.team_name}</strong> (Owner: ${team.owner_username})
            </div>
            <div>
                <button data-team-id="${team.team_id}">View Stats</button>
            </div>
        `;
        teamsListDiv.appendChild(teamItem);
    });
}

// NOTE: You still need to implement the backend endpoint: GET /api/league/<league_id>/details