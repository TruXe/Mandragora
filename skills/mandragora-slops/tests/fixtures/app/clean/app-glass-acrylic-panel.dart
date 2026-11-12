import 'package:flutter/material.dart';

class NowPlaying extends StatelessWidget {
  const NowPlaying({super.key});

  @override
  Widget build(BuildContext context) {
    return Container(
      color: const Color(0xFF1F1F23),
      padding: const EdgeInsets.all(16),
      child: const Column(
        children: [
          Text('Now playing'),
          Text('Track 04  3:12 / 5:40'),
        ],
      ),
    );
  }
}
