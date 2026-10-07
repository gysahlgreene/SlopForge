from processing.comfy_generate import find_save_node


def test_comfy_generation_selects_only_image_outputs():
    assert find_save_node({"1": {"class_type": "SaveVideo"}}) is None
    assert find_save_node({"1": {"class_type": "SaveImage"}}) == "1"
