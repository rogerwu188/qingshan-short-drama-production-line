import unittest

from tools.image_model_adapter import compile_labeled_flat_identity_transport


class ConcealedIdentityTransportTests(unittest.TestCase):
    def test_fully_concealed_identity_never_requests_face_features(self):
        bindings = [{
            "role": "character", "entity_id": "CHAR-MASKED",
            "path": "masked.png", "sha256": "abc",
            "identity_visual_contract": "FULLY_CONCEALED_IDENTITY",
        }]
        sequence, contract, prompt = compile_labeled_flat_identity_transport("TASK-1", bindings, "body")
        self.assertEqual(sequence[0]["identity_visual_contract"], "FULLY_CONCEALED_IDENTITY")
        self.assertEqual(contract["authority_map"], {"CHAR-MASKED": "@图片1"})
        self.assertIn("全封闭头盔", prompt)
        self.assertIn("不得摘盔", prompt)
        self.assertNotIn("只定义该人物的脸型", prompt)

    def test_face_visible_identity_keeps_existing_contract(self):
        bindings = [{
            "role": "character", "entity_id": "CHAR-VISIBLE",
            "path": "visible.png", "sha256": "def",
        }]
        _, _, prompt = compile_labeled_flat_identity_transport("TASK-2", bindings, "body")
        self.assertIn("只定义该人物的脸型、五官比例、年龄与稳定身份", prompt)


if __name__ == "__main__":
    unittest.main()
