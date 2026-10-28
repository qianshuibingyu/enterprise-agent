from alembic import context
from sqlalchemy import create_engine, pool

from app.models.base import Base
from app.models.user import User, UserSession  # noqa: F401
from app.models.business import (  # noqa: F401
    ChannelAccount,
    ChannelGrant,
    Inquiry,
    InquiryAttachment,
    InternalNotification,
    InquiryEvent,
    Message,
    MessageAttachment,
)

config = context.config
target_metadata = Base.metadata

# 定义离线迁移函数，不直接连接数据库
def run_migrations_offline() -> None:
    # 配置 Alembic 的离线迁移环境
    context.configure(
        url="postgresql+psycopg://",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle":"named"},
    )
    # 开始一个 Alembic 迁移事务
    with context.begin_transaction():
        context.run_migrations()

# 定义在线迁移函数，需要连接数据库
def run_migrations_online() -> None:
    from app.database import get_database_url

    # 根据配置创建 SQLAlchemy 数据库引擎
    connectable = create_engine(
        get_database_url(),
        poolclass=pool.NullPool,
    )
    # 建立数据库连接并自动关闭连接
    with connectable.connect() as connection:
        # 配置 Alembic 的在线迁移环境
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        # 开始一个 Alembic 迁移事务
        with context.begin_transaction():
            context.run_migrations()

# 判断当前是否处于离线迁移模式
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()