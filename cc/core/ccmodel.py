# Case Conductor is a Test Case Management system.
# Copyright (C) 2011 uTest Inc.
#
# This file is part of Case Conductor.
#
# Case Conductor is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Case Conductor is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Case Conductor.  If not, see <http://www.gnu.org/licenses/>.
"""
Common model behavior for all Case Conductor models.

Soft-deletion (including cascade) and tracking of user and timestamp for model
creation, modification, and soft-deletion.

"""
import datetime

from django.db import models, router
from django.db.models.deletion import Collector
from django.db.models.query import QuerySet

from django.contrib.auth.models import User



def utcnow():
    return datetime.datetime.utcnow()



class SoftDeleteCollector(Collector):
    """
    A variant of Django's default delete-cascade collector that implements soft
    delete.

    """
    def collect(self, objs, *args, **kwargs):
        """
        Collect ``objs`` and dependent objects.

        We override in order to store "root" objects for undelete.

        """
        if kwargs.get("source", None) is None:
            self.root_objs = objs
        super(SoftDeleteCollector, self).collect(objs, *args, **kwargs)


    def delete(self, user=None):
        """
        Soft-delete all collected instances.

        """
        now = utcnow()
        for model, instances in self.data.iteritems():
            pk_list = [obj.pk for obj in instances]
            model._base_manager.filter(
                pk__in=pk_list, deleted_on__isnull=True).update(
                deleted_by=user, deleted_on=now)


    def undelete(self, user=None):
        """
        Undelete all collected instances that were deleted.

        """
        # timestamps on which root obj(s) were deleted; only cascade items also
        # deleted in one of these same cascade batches should be undeleted.
        deletion_times = set([o.deleted_on for o in self.root_objs])
        for model, instances in self.data.iteritems():
            pk_list = [obj.pk for obj in instances]
            model._base_manager.filter(
                pk__in=pk_list, deleted_on__in=deletion_times).update(
                deleted_by=None, deleted_on=None)



class CCQuerySet(QuerySet):
    """
    Implements modification tracking and soft deletes on bulk update/delete.

    """
    def create(self, *args, **kwargs):
        """
        Creates, saves, and returns a new object with the given kwargs.
        """
        user = kwargs.pop("user", None)
        kwargs["created_by"] = user
        kwargs["modified_by"] = user
        return super(CCQuerySet, self).create(*args, **kwargs)


    def update(self, *args, **kwargs):
        """
        Update all objects in this queryset with modifications in ``kwargs``.

        """
        kwargs["modified_by"] = kwargs.pop("user", None)
        kwargs["modified_on"] = utcnow()
        return super(CCQuerySet, self).update(*args, **kwargs)


    def delete(self, user=None):
        """
        Soft-delete all objects in this queryset.

        """
        collector = SoftDeleteCollector(using=self._db)
        collector.collect(self)
        collector.delete(user)


    def undelete(self, user=None):
        """
        Undelete all objects in this queryset.

        """
        collector = SoftDeleteCollector(using=self._db)
        collector.collect(self)
        collector.undelete(user)



class CCManager(models.Manager):
    """Pass-through manager to ensure ``CCQuerySet`` is always used."""
    def get_query_set(self):
        """Return a ``CCQuerySet`` for all queries."""
        return CCQuerySet(self.model, using=self._db)



class NotDeletedCCManager(CCManager):
    """Manager that returns only not-deleted objects."""
    def get_query_set(self):
        return super(NotDeletedCCManager, self).get_query_set().filter(
            deleted_on__isnull=True)



class CCModel(models.Model):
    """
    Common base abstract model for all Case Conductor models.

    Tracks user and timestamp for creation, modification, and (soft) deletion.

    """
    created_on = models.DateTimeField(default=utcnow)
    created_by = models.ForeignKey(
        User, blank=True, null=True, related_name="+")

    modified_on = models.DateTimeField(default=utcnow)
    modified_by = models.ForeignKey(
        User, blank=True, null=True, related_name="+")
    deleted_on = models.DateTimeField(db_index=True, blank=True, null=True)
    deleted_by = models.ForeignKey(
        User, blank=True, null=True, related_name="+")



    # default manager returns all objects, so admin can see all
    everything = CCManager()
    # ...but "objects", for use in most code, returns only not-deleted
    objects = NotDeletedCCManager()


    def save(self, *args, **kwargs):
        """
        Save this instance, recording modified timestamp and user.

        """
        user = kwargs.pop("user", None)
        now = utcnow()
        if self.pk is None and user is not None:
            self.created_by = user
        if self.pk or user is not None:
            self.modified_by = user
        self.modified_on = now
        return super(CCModel, self).save(*args, **kwargs)


    def clone(self, cascade=None, overrides=None):
        """
        Clone this instance and return the new, cloned instance.

        If the instance has a ``name`` field, "Cloned: " will be prepended to
        its value in the cloned instance.

        ``overrides`` should be a dictionary of override values for fields on
        the cloned instance.

        M2M or reverse FK relations listed in ``cascade`` iterable will be
        cascade-cloned. By default, if not listed in ``cascade``, m2m/reverse
        FKs will effectively be cleared (as the remote object will still be
        pointing to the original instance, not the cloned one.)

        If ``cascade`` is a dictionary, keys are m2m/reverse-FK accessor names,
        and values are a callable that takes the queryset of all related
        objects and returns those that should be cloned.

        """
        if cascade is None:
            cascade = {}
        else:
            try:
                cascade.iteritems
            except AttributeError:
                cascade = dict((i, lambda qs: qs) for i in cascade)

        if overrides is None:
            overrides = {}

        clone = self.__class__()

        for field in self._meta.fields:
            if field.primary_key:
                continue
            val = overrides.get(field.name, getattr(self, field.name))
            if field.name == "name":
                val = "Cloned: %s" % val
            setattr(clone, field.name, val)

        clone.save(force_insert=True)

        for name, filter_func in cascade.items():
            mgr = getattr(self, name)
            if mgr.__class__.__name__ == "ManyRelatedManager": # M2M
                clone_mgr = getattr(clone, name)
                clone_mgr.add(*filter_func(mgr.all()))
            elif mgr.__class__.__name__ == "RelatedManager": # reverse FK
                reverse_name = getattr(self.__class__, name).related.field.name
                for obj in filter_func(mgr.all()):
                    obj.clone(overrides={reverse_name: clone})
            else:
                raise ValueError(
                    "Cannot cascade-clone '{0}'; "
                    "not a many-to-many or reverse foreignkey.".format(name))

        return clone


    def delete(self, user=None):
        """
        (Soft) delete this instance.

        """
        self._collector.delete(user)


    def undelete(self, user=None):
        """
        Undelete this instance.

        """
        self._collector.undelete(user)


    @property
    def _collector(self):
        """Returns populated delete-cascade collector."""
        db = router.db_for_write(self.__class__, instance=self)
        collector = SoftDeleteCollector(using=db)
        collector.collect([self])
        return collector


    class Meta:
        abstract = True



class TeamModel(CCModel):
    """
    Model which may have its own team or inherit team from parent.

    If ``has_team`` is True, ``own_team`` is this instance's team. If False,
    the parent's team is used instead.

    If a ``TeamModel`` does not implement a ``parent`` property that returns
    its "parent" for purposes of team inheritance, it will be considered to be
    the top of the inheritance chain and won't inherit a team.

    """
    has_team = models.BooleanField(default=False)
    own_team = models.ManyToManyField(User, blank=True)


    @property
    def team(self):
        if self.has_team or self.parent is None:
            return self.own_team
        return self.parent.team


    def add_to_team(self, *users):
        """Add given users to this object's team (not to parent team)."""
        self.own_team.add(*users)
        self.has_team = True
        self.save()


    @property
    def parent(self):
        return None


    class Meta:
        abstract = True
