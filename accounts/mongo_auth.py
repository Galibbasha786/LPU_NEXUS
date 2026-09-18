# accounts/mongo_auth.py
from django.contrib.auth.hashers import make_password, check_password
from core.mongo import users, student_profiles
from core.utils import now, to_object_id


# =====================================================
#  FIXED ADMIN EMAIL (only this email can be admin)
# =====================================================
FIXED_ADMIN_EMAIL = "syedsunnygalibbasha786@gmail.com"


def create_student(email, password, full_name, registration_number,
                   department='', year='', id_card_path=''):
    """Self-registration path. Role is forced to 'student'."""
    email = email.strip().lower()

    if users().find_one({'email': email}):
        return None, "Email already registered."

    if users().find_one({'registration_number': registration_number}):
        return None, "This LPU registration number is already registered."

    if len(password) < 6:
        return None, "Password must be at least 6 characters."

    if not registration_number:
        return None, "LPU registration number is required."

    user_doc = {
        'email': email,
        'password_hash': make_password(password),
        'full_name': full_name.strip(),
        'role': 'student',
        'active': True,
        'created_at': now(),
        'updated_at': now(),
    }
    result = users().insert_one(user_doc)

    student_profiles().insert_one({
        'user_id': result.inserted_id,
        'registration_number': registration_number.strip(),
        'department': department.strip(),
        'year': year.strip(),
        'id_card_path': id_card_path,      # relative path under /media/
        'created_at': now(),
    })

    user_doc['_id'] = result.inserted_id
    return user_doc, None


def create_staff(email, password, full_name, department='',
                 designation='', phone=''):
    """Admin-only path. Role is forced to 'staff'."""
    email = email.strip().lower()

    if users().find_one({'email': email}):
        return None, "Email already registered."

    if len(password) < 6:
        return None, "Password must be at least 6 characters."

    user_doc = {
        'email': email,
        'password_hash': make_password(password),
        'full_name': full_name.strip(),
        'role': 'staff',
        'active': True,
        'department': department.strip(),
        'designation': designation.strip(),
        'phone': phone.strip(),
        'created_by_admin': True,
        'created_at': now(),
        'updated_at': now(),
    }
    result = users().insert_one(user_doc)
    user_doc['_id'] = result.inserted_id
    return user_doc, None


def create_admin_if_missing(password='admin123'):
    """Ensures the one-and-only admin exists. Called from seed command."""
    if users().find_one({'email': FIXED_ADMIN_EMAIL}):
        return None
    user_doc = {
        'email': FIXED_ADMIN_EMAIL,
        'password_hash': make_password(password),
        'full_name': 'Syed Sunny Galib Basha',
        'role': 'admin',
        'active': True,
        'created_at': now(),
        'updated_at': now(),
    }
    users().insert_one(user_doc)
    return user_doc


def authenticate_user(email, password):
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


def get_student_profile(user_id):
    oid = to_object_id(user_id)
    if not oid:
        return None
    return student_profiles().find_one({'user_id': oid})


def list_staff():
    return list(users().find({'role': 'staff'}).sort('created_at', -1))


def list_students():
    return list(users().find({'role': 'student'}).sort('created_at', -1))