from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class CalculatorInputError(ValueError):
    """Raised when a student calculator receives invalid input."""


def _decimal(value, label):
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise CalculatorInputError(f'{label} must be a valid number.') from None
    if not number.is_finite():
        raise CalculatorInputError(f'{label} must be a valid number.')
    return number


def _rounded(value, places):
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def calculate_attendance(total_classes, classes_attended, classes_remaining):
    try:
        total = int(str(total_classes).strip())
        attended = int(str(classes_attended).strip())
        remaining = int(str(classes_remaining).strip())
    except (TypeError, ValueError):
        raise CalculatorInputError('Enter whole numbers for all class counts.') from None

    if total < 1:
        raise CalculatorInputError('Total classes held must be at least 1.')
    if attended < 0 or attended > total:
        raise CalculatorInputError(
            'Classes attended must be between 0 and total classes held.'
        )
    if remaining < 0:
        raise CalculatorInputError('Classes remaining cannot be negative.')

    attendance_percent = _rounded(Decimal(attended * 100) / Decimal(total), '.01')
    classes_needed_to_recover = max(0, 3 * total - 4 * attended)
    required_attendance = (
        (3 * (total + remaining) + 3) // 4 - attended
    )
    can_reach_target = required_attendance <= remaining

    if can_reach_target:
        absences_available = (
            4 * (attended + remaining) - 3 * (total + remaining)
        ) // 4
        max_classes_to_miss = min(remaining, max(0, absences_available))
        classes_to_attend = remaining - max_classes_to_miss
    else:
        max_classes_to_miss = None
        classes_to_attend = remaining

    projected_percent = _rounded(
        Decimal((attended + remaining) * 100) / Decimal(total + remaining),
        '.01',
    )
    return {
        'total_classes': total,
        'classes_attended': attended,
        'classes_remaining': remaining,
        'attendance_percent': attendance_percent,
        'classes_needed_to_recover': classes_needed_to_recover,
        'can_reach_target': can_reach_target,
        'max_classes_to_miss': max_classes_to_miss,
        'classes_to_attend': classes_to_attend,
        'projected_percent_if_attend_all': projected_percent,
    }


def grade_for_points(points):
    if points == Decimal('10'):
        return '10.000 Grade Points'
    if points >= Decimal('9'):
        return 'A+ (Excellent)'
    if points >= Decimal('8'):
        return 'A (Very Good)'
    if points >= Decimal('7'):
        return 'B+ (Good)'
    if points >= Decimal('6'):
        return 'B (Above Average)'
    if points >= Decimal('5'):
        return 'C (Average)'
    if points >= Decimal('4'):
        return 'D (Pass)'
    return 'F (Fail)'


def calculate_gpa(
    course_names,
    course_credits,
    course_marks,
    course_types,
    cumulative=False,
    previous_gpa='',
    previous_credits='',
):
    lengths = {
        len(course_names), len(course_credits), len(course_marks), len(course_types),
    }
    if len(lengths) != 1:
        raise CalculatorInputError('Course details are incomplete. Please try again.')
    if not course_names:
        raise CalculatorInputError('Add at least one course to calculate GPA.')

    weighted_points = Decimal('0')
    graded_credits = Decimal('0')
    rows = []
    for index, (name, credits_value, marks_value, course_type) in enumerate(
        zip(course_names, course_credits, course_marks, course_types),
        start=1,
    ):
        name = name.strip()
        if not name:
            raise CalculatorInputError(f'Enter a name for course {index}.')
        if course_type == 'satisfactory':
            rows.append({
                'name': name,
                'credits': None,
                'marks': None,
                'grade_point': None,
                'grade': 'S (Satisfactory)',
                'satisfactory': True,
            })
            continue
        if course_type != 'graded':
            raise CalculatorInputError(f'Choose a valid grading type for {name}.')

        credits = _decimal(credits_value, f'Credits for {name}')
        marks = _decimal(marks_value, f'Marks for {name}')
        if credits <= 0:
            raise CalculatorInputError(f'Credits for {name} must be greater than 0.')
        if marks < 0 or marks > 100:
            raise CalculatorInputError(f'Marks for {name} must be between 0 and 100.')

        points = marks / Decimal('10')
        weighted_points += points * credits
        graded_credits += credits
        rows.append({
            'name': name,
            'credits': _rounded(credits, '.001'),
            'marks': _rounded(marks, '.01'),
            'grade_point': _rounded(points, '.001'),
            'grade': grade_for_points(points),
            'satisfactory': False,
        })

    if graded_credits == 0:
        raise CalculatorInputError(
            'Add at least one credit-bearing course; S courses are excluded from GPA.'
        )

    prior_credits = Decimal('0')
    if cumulative:
        previous_credits = str(previous_credits).strip()
        previous_gpa = str(previous_gpa).strip()
        if previous_credits and not previous_gpa:
            raise CalculatorInputError(
                'Enter your previous CGPA when previous graded credits are provided.'
            )
        if previous_gpa:
            prior_gpa_value = _decimal(previous_gpa, 'Previous CGPA')
            if prior_gpa_value < 0 or prior_gpa_value > 10:
                raise CalculatorInputError('Previous CGPA must be between 0 and 10.')
        else:
            prior_gpa_value = Decimal('0')
        if previous_credits:
            prior_credits = _decimal(previous_credits, 'Previous graded credits')
            if prior_credits < 0:
                raise CalculatorInputError('Previous graded credits cannot be negative.')
        weighted_points += prior_gpa_value * prior_credits
        graded_credits += prior_credits

    return {
        'courses': rows,
        'graded_credits': _rounded(graded_credits, '.001'),
        'weighted_points': _rounded(weighted_points, '.001'),
        'gpa': _rounded(weighted_points / graded_credits, '.001'),
        'cumulative': cumulative,
    }
