from dataclasses import dataclass, field
from typing import Dict, Any, Callable, Optional, Type, List, Union, Mapping


@dataclass
class Config:
    type_hooks: Mapping[Union[Type, object], Callable[[Any], Any]] = field(default_factory=dict)
    cast: List[Type] = field(default_factory=list)
    forward_references: Optional[Dict[str, Any]] = None
    check_types: bool = True
    strict: bool = False
    strict_unions_match: bool = False
    allow_missing_fields_as_none: bool = False
