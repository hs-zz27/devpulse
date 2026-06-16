import enum


class PRState(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class PRSeverity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class PRCategory(str, enum.Enum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    BUG = "bug"
    STYLE = "style"
    BEST_PRACTICES = "best_practices"
    TESTING = "testing"
    OTHERS = "others"


class DeploymentEnvironment(str, enum.Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    PREVIEW = "preview"


class DeploymentStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    IN_PROGRESS = "in_progress"
