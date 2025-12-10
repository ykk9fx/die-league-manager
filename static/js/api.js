// C:\projects\league-manager-api\static\js\api.js

const API = {
    // Core method for all API calls
    async json(url, opts = {}) {
        // CRITICAL FIX: Ensure session cookies are sent with every request
        const fetchOptions = {
            ...opts,
            headers: {
                'Content-Type': 'application/json',
                ...(opts.headers || {})
            },
            credentials: 'include' // <-- THIS IS REQUIRED FOR FLASK SESSION COOKIES
        };

        const res = await fetch(url, fetchOptions);
        const text = await res.text();

        try {
            const data = text ? JSON.parse(text) : null;
            
            if (!res.ok) {
                // If response status is an error (4xx or 5xx)
                throw Object.assign(new Error(data?.error || res.statusText), { status: res.status, body: data });
            }
            return data;
        } catch (e) {
            // Handle parsing errors or network errors
            if (!res.ok) throw Object.assign(new Error(text || res.statusText), { status: res.status });
            throw e;
        }
    },
    
    // HTTP Method Helpers
    get(url) { return this.json(url) },
    
    post(url, body) { 
        return this.json(url, { 
            method: 'POST', 
            body: JSON.stringify(body) 
        });
    },
    
    put(url, body) { 
        return this.json(url, { 
            method: 'PUT', 
            body: JSON.stringify(body) 
        });
    },
    
    del(url) { return this.json(url, { method: 'DELETE' }) }
};
window.API = API;