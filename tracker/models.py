from django.db import models
from django.contrib.auth.models import User

class RouteLog(models.Model):
    user         = models.ForeignKey(
                       User,
                       on_delete=models.CASCADE,
                       related_name='routes'
                   )
    created_at   = models.DateTimeField(auto_now_add=True)
    start_lat    = models.FloatField()
    start_lon    = models.FloatField()
    end_lat      = models.FloatField()
    end_lon      = models.FloatField()
    route_points = models.JSONField(default=list)
    total_points = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Route by {self.user.username} on {self.created_at}'
