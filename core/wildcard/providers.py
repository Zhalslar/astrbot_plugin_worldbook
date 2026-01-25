from datetime import datetime


def register_builtin(resolver):
    resolver.register("msg", lambda ctx: ctx.get("msg"))
    resolver.register("user", lambda ctx: ctx.get("user"))
    resolver.register("umo", lambda ctx: ctx.get("umo"))
    resolver.register(
        "time",
        lambda ctx: datetime.now().strftime("%H:%M:%S"),
    )
