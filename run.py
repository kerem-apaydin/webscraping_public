from flask import Flask
from app import create_app

app = create_app()

@app.after_request
def add_cache_headers(response):
    if 'Content-Type' in response.headers and 'text/html' not in response.headers['Content-Type']:
        response.cache_control.max_age = 604800  
    return response

if __name__ == '__main__':
    app.run(debug=True, port=5000)