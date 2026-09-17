# accounts/mongo_auth.py
from django.contrib.auth.hashers import make_password, check_password
from core.mongo import users, student_profiles
from core.utils import now, to_object_id


def create_user(email, password, full_name, role='student', **extra):
    """
    Create a user in MongoDB.
    Returns (user_doc, error_message)
    """
    email = email.strip().lower()

    if users().find_one({'email': email}):
        return None, "Email already registered."

    if len(password) < 6:
        return None, "Password must be at least 6 characters."

    user_doc = {
        'email': email,
        'password_hash': make_password(password),
        'full_name': full_name.strip(),
        'role': role,                      # student | staff | admin
        'active': True,
        'created_at': now(),
        'updated_at': now(),
    }
    result = users().insert_one(user_doc)
    user_doc['_id'] = result.inserted_id

    # Student profile stub
    if role == 'student':
        student_profiles().insert_one({
            'user_id': result.inserted_id,
            'registration_number': extra.get('registration_number', ''),
            'department': extra.get('department', ''),
            'year': extra.get('year', ''),
            'created_at': now(),
        })

    return user_doc, None


def authenticate_user(email, password):
    """
    Verify credentials. Returns user_doc or None.
    """
    email = email.strip().lower()
    user = users().find_one({'email': email})
    if not user:
        return None
    if not user.get('active', True):
        return None
    if not check_password(password, user['password_hash']):
        return None
    return user


def get_user_by_id(user_id):
    oid = to_object_id(user_id)
    if not oid:
        return None
    return users().find_one({'_id': oid})


def set_user_password(user_id, new_password):
    oid = to_object_id(user_id)
    users().update_one(
        {'_id': oid},
        {'$set': {
            'password_hash': make_password(new_password),
            'updated_at': now(),
        }}
    )