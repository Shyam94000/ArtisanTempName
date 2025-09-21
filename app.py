import os
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, Response
from pymongo import MongoClient
from gridfs import GridFS
from bson import ObjectId
from flask_bcrypt import Bcrypt

# =================================================================
# 1. INITIALIZATION & CONFIGURATION
# =================================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-very-secret-and-random-string-for-sessions'
bcrypt = Bcrypt(app)

# =================================================================
# 2. DATABASE CONNECTION
# =================================================================
try:
    client = MongoClient("mongodb://localhost:27017/")
    db = client["ArtisanCollectiveDB"]
    fs = GridFS(db)
    users_collection = db["users"]
    products_collection = db["products"]
    client.server_info() 
    print("✅ MongoDB connection successful.")
except Exception as e:
    print(f"❌ Could not connect to MongoDB. Error: {e}")

# =================================================================
# 3. ROUTES TO SERVE HTML PAGES
# =================================================================
@app.route('/')
def home():
    # Assuming you have an index.html for the landing page
    return render_template('index.html')

@app.route('/join')
def join_page():
    return render_template('join.html')

@app.route('/explore')
def explore_page():
    return render_template('explore_artisans.html')

@app.route('/artisan-profile')
def artisan_profile_page():
    return render_template('view.html')


@app.route('/login')
def login_page():
    # Assuming you have a login.html
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('login_page'))
    # Assuming you have a dashboard.html
    return render_template('dashboard.html', username=session.get('username'))

@app.route('/logout')
def logout():
    session.clear()
    print("✅ User logged out.")
    return redirect(url_for('home'))

# =================================================================
# 4. API ENDPOINTS
# =================================================================

# --- User Management API ---
@app.route('/api/signup', methods=['POST'])
def api_signup():
    try:
        data = request.form
        username = data.get('username')
        password = data.get('password')
        video_file = request.files.get('video')
        profile_image_file = request.files.get('profileImage')

        if not all([username, password, data.get('name')]):
            return jsonify({"status": "error", "message": "Missing required fields."}), 400

        if users_collection.find_one({"username": username}):
            return jsonify({"status": "error", "message": "Username already exists."}), 409

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        video_id = None 
        if video_file:
            video_id = fs.put(video_file, filename=f"{username}_video")
            
        profile_image_id = None
        if profile_image_file:
            profile_image_id = fs.put(profile_image_file, filename=f"{username}_profile_pic")

        user_doc = {
            "username": username, "password": hashed_password, "fullname": data.get('name'),
            "shopname": data.get('shop'), "address": data.get('address'),
            "geolocation": data.get('geo'), "story": data.get('story'), 
            "video_id": video_id,
            "profile_image_id": profile_image_id,
            "contactNumber": data.get('contactNumber'),
            "rating": 0, "ratingCount": 0
        }
        users_collection.insert_one(user_doc)
        
        return jsonify({"status": "success", "message": "Signup successful! Please log in."}), 201
    except Exception as e:
        print(f"❌ SIGNUP ERROR: {e}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    try:
        data = request.get_json()
        username = data.get('username')
        user = users_collection.find_one({"username": username})
        
        if user and bcrypt.check_password_hash(user['password'], data.get('password')):
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            return jsonify({"status": "success", "message": "Login successful!"}), 200
        else:
            return jsonify({"status": "error", "message": "Invalid username or password."}), 401
    except Exception as e:
        print(f"❌ LOGIN ERROR: {e}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

@app.route('/api/artisans/<artisan_id>/rate', methods=['POST'])
def rate_artisan(artisan_id):
    try:
        data = request.get_json()
        new_rating = float(data.get('rating'))
        
        if not 1 <= new_rating <= 5:
            return jsonify({"status": "error", "message": "Rating must be between 1 and 5."}), 400

        artisan = users_collection.find_one({'_id': ObjectId(artisan_id)})
        if not artisan:
            return jsonify({"status": "error", "message": "Artisan not found."}), 404

        old_avg = artisan.get('rating', 0)
        old_count = artisan.get('ratingCount', 0)

        new_count = old_count + 1
        new_avg = ((old_avg * old_count) + new_rating) / new_count

        users_collection.update_one(
            {'_id': ObjectId(artisan_id)},
            {'$set': {'rating': new_avg, 'ratingCount': new_count}}
        )

        return jsonify({
            "status": "success",
            "message": "Rating submitted.",
            "newRating": round(new_avg, 2),
            "ratingCount": new_count
        }), 200
    except Exception as e:
        print(f"❌ RATING ERROR: {e}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500

# --- Profile and Product Management APIs ---
@app.route('/api/profile', methods=['GET', 'POST'])
def api_profile():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Authentication required."}), 401
    
    user_id = ObjectId(session['user_id'])

    if request.method == 'GET':
        user = users_collection.find_one({'_id': user_id}, {'password': 0})
        if not user:
            return jsonify({"status": "error", "message": "User not found."}), 404
        user['_id'] = str(user['_id'])
        return jsonify(user)

    if request.method == 'POST':
        data = request.get_json()
        update_data = {
            "fullname": data.get('fullname'), "shopname": data.get('shopname'),
            "address": data.get('address'), "story": data.get('story'),
            "contactNumber": data.get('contactNumber')
        }
        users_collection.update_one({'_id': user_id}, {'$set': update_data})
        return jsonify({"status": "success", "message": "Profile updated successfully."})

@app.route('/api/products', methods=['POST'])
def add_product():
    if 'user_id' not in session: return jsonify({"status": "error", "message": "Authentication required."}), 401
    try:
        data = request.form; images = request.files.getlist('productImages')
        image_ids = [fs.put(i, filename=f"prod_{i.filename}") for i in images]
        doc = {"artisan_id": ObjectId(session['user_id']), "name": data.get('name'), "description": data.get('description'), "price": float(data.get('price')), "image_ids": image_ids}
        products_collection.insert_one(doc)
        return jsonify({"status": "success", "message": "Product uploaded!"}), 201
    except Exception as e: print(f"❌ ADD PROD ERR: {e}"); return jsonify({"status": "error", "message": "Failed to add product."}), 500

@app.route('/api/products/<product_id>', methods=['PUT', 'DELETE'])
def manage_product(product_id):
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Authentication required."}), 401

    try:
        product = products_collection.find_one({
            "_id": ObjectId(product_id),
            "artisan_id": ObjectId(session['user_id'])
        })
        if not product:
            return jsonify({"status": "error", "message": "Product not found or you do not have permission to modify it."}), 404

        if request.method == 'DELETE':
            # Delete images from GridFS
            for image_id in product.get('image_ids', []):
                fs.delete(image_id)
            products_collection.delete_one({"_id": ObjectId(product_id)})
            return jsonify({"status": "success", "message": "Product deleted successfully."}), 200

        if request.method == 'PUT':
            data = request.form
            update_fields = {
                'name': data.get('name'),
                'description': data.get('description'),
                'price': float(data.get('price'))
            }
            
            # Image handling: if new images are uploaded, they replace old ones.
            new_images = request.files.getlist('productImages')
            if new_images:
                # Delete old images
                for image_id in product.get('image_ids', []):
                    fs.delete(image_id)
                # Add new images
                image_ids = [fs.put(i, filename=f"prod_{i.filename}") for i in new_images]
                update_fields['image_ids'] = image_ids

            products_collection.update_one(
                {"_id": ObjectId(product_id)},
                {"$set": update_fields}
            )
            return jsonify({"status": "success", "message": "Product updated successfully."}), 200

    except Exception as e:
        print(f"❌ MANAGE PROD ERR: {e}")
        return jsonify({"status": "error", "message": "An internal server error occurred."}), 500


@app.route('/api/my-products', methods=['GET'])
def get_my_products():
    if 'user_id' not in session: return jsonify({"status": "error", "message": "Authentication required."}), 401
    try:
        prods = list(products_collection.find({"artisan_id": ObjectId(session['user_id'])}))
        for p in prods:
            p['_id'], p['artisan_id'] = str(p['_id']), str(p['artisan_id'])
            p['image_ids'] = [str(i) for i in p['image_ids']]
        return jsonify(prods)
    except Exception as e: print(f"❌ GET MY PRODS ERR: {e}"); return jsonify({"status": "error", "message": "Could not get products."}), 500

@app.route('/api/products', methods=['GET'])
def get_all_products():
    try:
        prods = list(products_collection.find({}))
        for p in prods:
            artisan = users_collection.find_one({"_id": p['artisan_id']}, {"shopname": 1, "contactNumber": 1})
            p['shopname'] = artisan.get('shopname', 'N/A') if artisan else 'N/A'
            p['contactNumber'] = artisan.get('contactNumber', 'N/A') if artisan else 'N/A'
            p['_id'], p['artisan_id'] = str(p['_id']), str(p['artisan_id'])
            p['image_ids'] = [str(i) for i in p['image_ids']]
        return jsonify(prods)
    except Exception as e: print(f"❌ GET ALL PRODS ERR: {e}"); return jsonify({"status": "error", "message": "Could not get products."}), 500

@app.route('/api/artisans', methods=['GET'])
def get_artisans():
    try:
        artisans = list(users_collection.find({}, {"password": 0}))
        for artisan in artisans:
            artisan['_id'] = str(artisan['_id'])
            if artisan.get('video_id'): 
                artisan['video_id'] = str(artisan['video_id'])
            if artisan.get('profile_image_id'):
                artisan['profile_image_id'] = str(artisan['profile_image_id'])
        return jsonify(artisans)
    except Exception as e: 
        print(f"❌ GET ARTISANS ERR: {e}")
        return jsonify({"status": "error", "message": "Could not get artisan data."}), 500

@app.route('/api/artisan-profile/<artisan_id>', methods=['GET'])
def get_artisan_profile(artisan_id):
    try:
        artisan = users_collection.find_one({'_id': ObjectId(artisan_id)}, {'password': 0})
        if not artisan:
            return jsonify({"status": "error", "message": "Artisan not found."}), 404
            
        artisan['_id'] = str(artisan['_id'])
        if artisan.get('video_id'): artisan['video_id'] = str(artisan['video_id'])
        if artisan.get('profile_image_id'): artisan['profile_image_id'] = str(artisan['profile_image_id'])

        products = list(products_collection.find({"artisan_id": ObjectId(artisan_id)}))
        for p in products:
            p['_id'] = str(p['_id'])
            p['artisan_id'] = str(p['artisan_id'])
            p['image_ids'] = [str(i) for i in p['image_ids']]
            p['shopname'] = artisan.get('shopname', 'N/A')

        return jsonify({"artisan": artisan, "products": products})

    except Exception as e:
        print(f"❌ GET ARTISAN PROFILE ERR: {e}")
        return jsonify({"status": "error", "message": "Could not get artisan profile data."}), 500

# --- File Serving Routes ---
@app.route('/video/<video_id>')
def get_video(video_id):
    try: 
        grid_out = fs.get(ObjectId(video_id))
        return Response(grid_out, mimetype='video/mp4', content_type='video/mp4')
    except: 
        return "Video not found", 404

@app.route('/image/<image_id>')
def get_image(image_id):
    try: 
        grid_out = fs.get(ObjectId(image_id))
        return Response(grid_out, mimetype=grid_out.content_type)
    except: 
        return "Image not found", 404

# =================================================================
# 5. RUN THE APPLICATION
# =================================================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5010, debug=True)
