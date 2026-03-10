from django.db import models
from django.contrib.auth.models import User

class RouteLog(models.Model):

    user = models.ForeignKey(User, on_delete=models.CASCADE)

    created_at = models.DateTimeField(auto_now_add=True)
    
    start_lat = models.FloatField()
    start_lon = models.FloatField()

    end_lat = models.FloatField()
    end_lon = models.FloatField()

    route_points = models.JSONField()   # stores full GPS array

    total_points = models.IntegerField(default=0)

    def __str__(self):
        return f"Route {self.id} — {self.created_at}"
