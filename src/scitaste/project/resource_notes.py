"""Replace one named resource paragraph without erasing other task notes."""


def replace_resource_note(text, name, note):
    if not name.strip() or "\n" in name or not note.strip() or "\n\n" in note:
        raise ValueError("Resource notes require one named paragraph")
    marker = f"\n\n{name}: "
    prefix, found, remainder = text.partition(marker)
    if not found:
        return text + marker + note
    _, boundary, suffix = remainder.partition("\n\n")
    return prefix + marker + note + (boundary + suffix if boundary else "")
