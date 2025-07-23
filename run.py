from flask import Flask
from app import create_app

app = create_app()

@app.after_request
def add_cache_headers(response):
    """Add cache-control headers for non-HTML responses."""
    if 'Content-Type' in response.headers and 'text/html' not in response.headers['Content-Type']:
        response.cache_control.max_age = 604800  # 7 days
    return response

if __name__ == '__main__':
    app.run(debug=app.config.get('DEBUG', False), host='0.0.0.0', port=app.config.get('PORT', 5000))