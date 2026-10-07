from django import forms
from django.contrib.auth.models import User

from .models import Counter, Provider, Review, Service


class JoinQueueForm(forms.Form):
    service = forms.ModelChoiceField(queryset=Service.objects.filter(active=True).select_related("provider"),
                                     empty_label="Select a service")
    priority = forms.ChoiceField(choices=[("0", "Normal"), ("2", "Priority lane (senior / differently-abled / pregnant)")],
                                 initial="0")


class RegisterForm(forms.Form):
    username = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    password = forms.CharField(widget=forms.PasswordInput, min_length=6)
    role = forms.ChoiceField(choices=[("CUSTOMER", "I am a customer"), ("PROVIDER", "I run a service business")])
    priority_eligible = forms.BooleanField(required=False, label="I am eligible for the priority lane")

    def clean_username(self):
        name = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=name).exists():
            raise forms.ValidationError("That username is taken.")
        return name


class ReviewForm(forms.ModelForm):
    rating = forms.IntegerField(min_value=1, max_value=5)

    class Meta:
        model = Review
        fields = ["rating", "comment"]


class ProviderForm(forms.ModelForm):
    open_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}), initial="09:00")
    close_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time"}), initial="17:00")

    class Meta:
        model = Provider
        fields = ["name", "category", "area", "address", "description", "open_time", "close_time"]


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ["provider", "name", "average_minutes", "price"]

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)
        if owner is not None:
            self.fields["provider"].queryset = Provider.objects.filter(owner=owner)


class CounterForm(forms.ModelForm):
    class Meta:
        model = Counter
        fields = ["service", "name"]

    def __init__(self, *args, services=None, **kwargs):
        super().__init__(*args, **kwargs)
        if services is not None:
            self.fields["service"].queryset = services
