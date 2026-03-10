from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User


def login_view(request):

    if request.user.is_authenticated:
        return redirect("tracker")

    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect("tracker")
        else:
            return render(request, "login.html", {"error": "Invalid username or password"})

    return render(request, "login.html")


def register_view(request):

    if request.user.is_authenticated:
        return redirect("tracker")

    if request.method == "POST":
        username  = request.POST.get("username", "").strip()
        email     = request.POST.get("email", "").strip()
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")

        ctx = {"username": username, "email": email}

        if not username:
            ctx["error"] = "Username is required."
            return render(request, "register.html", ctx)

        if len(password1) < 6:
            ctx["error"] = "Password must be at least 6 characters."
            return render(request, "register.html", ctx)

        if password1 != password2:
            ctx["error"] = "Passwords do not match."
            return render(request, "register.html", ctx)

        if User.objects.filter(username=username).exists():
            ctx["error"] = "Username is already taken."
            return render(request, "register.html", ctx)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password1,
        )
        login(request, user)
        return redirect("tracker")

    return render(request, "register.html")


def logout_view(request):
    logout(request)
    return redirect("login")