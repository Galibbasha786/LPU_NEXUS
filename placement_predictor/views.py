import logging

from django.shortcuts import render

from .forms import StudentPlacementForm
from .services import PlacementModelError, predict_placement

logger = logging.getLogger(__name__)


def _preparation_feedback(data):
    checks = [
        ("CGPA", data["CGPA"], 7.0, "Aim for a CGPA of 7 or higher."),
        ("Aptitude", data["Aptitude_Test_Score"], 60, "Practice aptitude tests and review weak question types."),
        ("Communication", data["Communication_Skills"], 60, "Build communication confidence with mock discussions and presentations."),
        ("Mock interview", data["Mock_Interview_Score"], 60, "Practice technical and behavioral mock interviews."),
        ("Projects", data["Projects_Count"], 2, "Build and document at least two substantial projects."),
        ("Internships", data["Internships"], 1, "Look for internship or practical industry experience."),
        ("DSA practice", data["DSA_Problems_Solved"], 100, "Set a regular data structures and algorithms practice goal."),
        ("Resume", data["Resume_Score"], 60, "Review your resume for clear impact, skills, and project outcomes."),
    ]
    strengths = [name for name, value, threshold, _ in checks if value >= threshold]
    suggestions = [tip for _, value, threshold, tip in checks if value < threshold]
    return strengths, suggestions[:4]


def predict(request):
    result = None
    form = StudentPlacementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            prediction_data = form.as_prediction_data()
            result = predict_placement(
                prediction_data,
                student_id=request.session.get("lpu_user_id"),
            )
            result["status_label"] = {
                "1": "Placed",
                "0": "Not placed",
            }.get(result["prediction"], f"Status {result['prediction']}")
            result["target_is_single_class"] = result.get("class_count", 2) < 2
            result["strengths"], result["suggestions"] = _preparation_feedback(prediction_data)
            if not result["suggestions"]:
                result["suggestions"] = [
                    "Refresh your resume with recent projects, skills, and measurable outcomes.",
                    "Keep practicing technical and behavioral interview questions each week.",
                    "Continue solving DSA problems and review concepts you find difficult.",
                    "Track applications and follow up with recruiters after interviews.",
                ]
        except PlacementModelError as error:
            form.add_error(None, str(error))
        except Exception as error:
            logger.exception("Placement prediction failed")
            form.add_error(
                None,
                "The prediction could not be completed. Check the server log for the underlying error; "
                "if MongoDB is unavailable, start it and verify MONGO_URI.",
            )
    if result:
        result["confidence_pct"] = round(result["confidence"] * 100, 1)
    return render(request, "placement_predictor/predict.html", {"form": form, "result": result})
