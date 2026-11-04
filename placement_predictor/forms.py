from django import forms


class StudentPlacementForm(forms.Form):
    age = forms.IntegerField(min_value=16, max_value=80, initial=20, widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "e.g. 20", "data-i18n-placeholder": "placement.placeholder.age"}))
    gender = forms.ChoiceField(choices=[("Male", "Male"), ("Female", "Female"), ("Other", "Other")], widget=forms.Select(attrs={"class": "form-select", "data-i18n-options": "placement.option.gender"}))
    college_tier = forms.ChoiceField(choices=[("Tier 1", "Tier 1"), ("Tier 2", "Tier 2"), ("Tier 3", "Tier 3")], widget=forms.Select(attrs={"class": "form-select", "data-i18n-options": "placement.option.college_tier"}))
    specialization = forms.ChoiceField(choices=[(x, x) for x in ("AI/ML", "Computer Science", "Civil", "Electronics", "Mechanical", "Electrical", "Information Technology", "Other")], widget=forms.Select(attrs={"class": "form-select", "data-i18n-options": "placement.option.specialization"}))
    cgpa = forms.FloatField(min_value=0, max_value=10, widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "placeholder": "e.g. 8.2", "data-i18n-placeholder": "placement.placeholder.cgpa"}))
    dsa_problems_solved = forms.IntegerField(min_value=0, max_value=10000, widget=forms.NumberInput(attrs={"class": "form-control", "placeholder": "Number solved", "data-i18n-placeholder": "placement.placeholder.dsa_problems_solved"}))
    internships = forms.IntegerField(min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "form-control"}))
    certifications = forms.IntegerField(min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "form-control"}))
    projects_count = forms.IntegerField(min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "form-control"}))
    communication_skills = forms.IntegerField(min_value=0, max_value=100, help_text="Score from 0 to 100", widget=forms.NumberInput(attrs={"class": "form-control"}))
    aptitude_test_score = forms.IntegerField(min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "form-control"}))
    leetcode_rating = forms.IntegerField(min_value=0, max_value=4000, widget=forms.NumberInput(attrs={"class": "form-control"}))
    github_contributions = forms.IntegerField(min_value=0, max_value=100000, widget=forms.NumberInput(attrs={"class": "form-control"}))
    hackathons_participated = forms.IntegerField(min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "form-control"}))
    ai_ml_skill_level = forms.IntegerField(min_value=0, max_value=10, widget=forms.NumberInput(attrs={"class": "form-control"}))
    system_design_knowledge = forms.IntegerField(min_value=0, max_value=10, widget=forms.NumberInput(attrs={"class": "form-control"}))
    resume_score = forms.IntegerField(min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "form-control"}))
    mock_interview_score = forms.IntegerField(min_value=0, max_value=100, widget=forms.NumberInput(attrs={"class": "form-control"}))

    def as_prediction_data(self):
        data = self.cleaned_data.copy()
        return {
            "Age": data["age"], "Gender": data["gender"], "College_Tier": data["college_tier"],
            "Specialization": data["specialization"], "CGPA": data["cgpa"],
            "DSA_Problems_Solved": data["dsa_problems_solved"], "Internships": data["internships"],
            "Certifications": data["certifications"], "Projects_Count": data["projects_count"],
            "Communication_Skills": data["communication_skills"], "Aptitude_Test_Score": data["aptitude_test_score"],
            "LeetCode_Rating": data["leetcode_rating"], "GitHub_Contributions": data["github_contributions"],
            "Hackathons_Participated": data["hackathons_participated"], "AI_ML_Skill_Level": data["ai_ml_skill_level"],
            "System_Design_Knowledge": data["system_design_knowledge"], "Resume_Score": data["resume_score"],
            "Mock_Interview_Score": data["mock_interview_score"],
        }
